"""Transcribe one selected clip for editable Hindi/English captions."""
import tempfile
import subprocess
import re
from pathlib import Path


def transcribe_clip(source, start, end, language='auto', model_name='small'):
    from faster_whisper import WhisperModel

    if language not in ('auto', 'hi', 'en'):
        raise ValueError('Choose Auto, Hindi or English')
    source = Path(source)
    with tempfile.TemporaryDirectory(prefix='cliphunter-captions-') as temp:
        audio = Path(temp) / 'speech.wav'
        subprocess.run([
            'ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', str(start),
            '-t', str(end-start), '-i', str(source), '-vn', '-ac', '1',
            '-ar', '16000', str(audio),
        ], check=True, timeout=180)
        model_root=source.parents[2]/'models'
        model_root.mkdir(exist_ok=True)
        try:
            model = WhisperModel(model_name, device='cpu', compute_type='int8', cpu_threads=4, download_root=str(model_root))
        except Exception:
            # A cached multilingual base model still supports Hindi and English
            # when the higher-accuracy model cannot be downloaded.
            model = WhisperModel('base', device='cpu', compute_type='int8', cpu_threads=4, local_files_only=True)
        def recognize(chosen):
            segments, details = model.transcribe(
                str(audio), language=chosen,
                beam_size=3, vad_filter=True, word_timestamps=True,
                repetition_penalty=1.1, no_repeat_ngram_size=3,
                condition_on_previous_text=False,
                initial_prompt='Speech may be in Hindi or English. Preserve the spoken language and script.',
            )
            return list(segments), details

        def quality(segments):
            weight=sum(max(.1,segment.end-segment.start) for segment in segments)
            logprob=sum(getattr(segment,'avg_logprob',-.5)*max(.1,segment.end-segment.start) for segment in segments)/max(.1,weight)
            content=' '.join(segment.text for segment in segments)
            tokens=re.findall(r'\S+',content.lower())
            diversity=len(set(tokens))/len(tokens) if tokens else 1
            return logprob-4*max(0,.4-diversity)-2*content.count('\ufffd')/max(1,len(content))

        pieces, info = recognize(None if language == 'auto' else language)
        confidence=round(info.language_probability,3)
        # Accented English and mixed speech can be misidentified as Hindi.
        # Retry English only when the automatic Hindi result is improbable or repetitive.
        if language == 'auto' and info.language == 'hi' and quality(pieces) < -1:
            english, english_info = recognize('en')
            if quality(english) > quality(pieces)+.15:
                pieces, info = english, english_info
                confidence=None  # A forced-language pass has no detection confidence.
        words=[]
        for piece in pieces:
            if piece.words:
                words.extend((start+w.start, start+w.end, w.word.strip()) for w in piece.words if w.word.strip())
            elif piece.text.strip():
                words.append((start+piece.start, start+piece.end, piece.text.strip()))
        captions=[]
        for first,last,text in words:
            if captions and len(captions[-1]['text'].split()) < 5 and first-captions[-1]['end'] < .7:
                captions[-1]['end']=round(min(end,last),3)
                captions[-1]['text']+=' '+text
            else:
                captions.append({'start':round(max(start,first),3),'end':round(min(end,last),3),'text':text})
        captions.sort(key=lambda line:line['start'])
        for index,line in enumerate(captions[:-1]):
            line['end']=min(line['end'],captions[index+1]['start'])
        captions=[line for line in captions if line['end']>line['start']]
        return {'language': info.language, 'confidence': confidence, 'segments': captions}
