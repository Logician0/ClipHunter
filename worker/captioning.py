"""Transcribe one selected clip with multilingual Whisper large-v3."""
import tempfile
import subprocess
import re
import json
import threading
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

TARGET_LANGUAGES = {'ar','bn','de','es','fa','fr','hi','id','it','ja','ko','ms','nl','pl','pt','ru','sv','th','tr','uk','ur','vi','zh'}


def translate_captions(captions, target, progress=None):
    """Download one official Argos English-to-target package, then translate locally."""
    from argostranslate import package, translate
    if not any(item.from_code=='en' and item.to_code==target for item in package.get_installed_packages()):
        if progress:progress(.80,'Finding translation model')
        package.update_package_index()
        model=next((item for item in package.get_available_packages()
                    if item.from_code=='en' and item.to_code==target),None)
        if model is None:raise ValueError(f'No offline translation model is available for {target}')
        link=next((url for url in model.links if urlsplit(url).scheme=='https'
                   and urlsplit(url).hostname=='argos-net.com' and urlsplit(url).path.startswith('/v1/')),None)
        if link is None:raise ValueError('No trusted download link for this translation model')
        destination=Path(os.environ['ARGOS_PACKAGES_DIR']).parent/'translation-downloads'
        destination.mkdir(parents=True,exist_ok=True)
        partial=destination/f'en_{target}.argosmodel.part'
        existing=partial.stat().st_size if partial.exists() else 0
        headers={'User-Agent':'ClipHunter/1.0'}
        if existing:headers['Range']=f'bytes={existing}-'
        request=Request(link,headers=headers)
        with urlopen(request,timeout=120) as response:
            if existing and response.status!=206:existing=0
            total=int(response.headers.get('Content-Range','').rsplit('/',1)[-1]) if response.status==206 else int(response.headers.get('Content-Length',0))
            with partial.open('ab' if existing else 'wb') as stream:
                received=existing
                while block:=response.read(1024*1024):
                    stream.write(block);received+=len(block)
                    if progress and total:progress(min(.95,.80+.15*received/total),'Downloading translation model')
        if total and received!=total:raise ValueError('Translation model download was incomplete; retry caption generation')
        package.install_from_path(partial)
        partial.unlink(missing_ok=True)
    if progress:progress(.95,'Translating captions')
    translated=[]
    for index,line in enumerate(captions):
        translated.append({**line,'text':translate.translate(line['text'],'en',target)})
        if progress:progress(.95+.04*(index+1)/max(1,len(captions)),'Translating captions')
    return translated
def transcribe_clip(source, start, end, language='auto', output='original', model_name='large-v3', progress=None):
    from faster_whisper import WhisperModel

    if not re.fullmatch(r'[a-z]{2,3}',language) and language!='auto':
        raise ValueError('Choose a supported spoken language or Auto detect')
    if output not in ('original','en') and output not in TARGET_LANGUAGES:
        raise ValueError('Choose a supported caption language')
    source = Path(source)
    with tempfile.TemporaryDirectory(prefix='cliphunter-captions-') as temp:
        audio = Path(temp) / 'speech.wav'
        subprocess.run([
            'ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', str(start),
            '-t', str(end-start), '-i', str(source), '-vn', '-ac', '1',
            '-ar', '16000', str(audio),
        ], check=True, timeout=180)
        data_root=source.parents[3] if source.parent.name.startswith('highlight-') else source.parents[2]
        model_root=data_root/'models'
        model_root.mkdir(exist_ok=True)
        stop=threading.Event()
        def model_progress():
            if model_name!='large-v3' or not progress:return
            cache=model_root/'models--Systran--faster-whisper-large-v3'
            expected=3_087_284_237
            while not stop.wait(1):
                trees=list((cache/'trees').glob('*.json')) if (cache/'trees').exists() else []
                if trees:
                    try:expected=int(json.loads(trees[0].read_text())['files']['model.bin']['size'])
                    except (ValueError,KeyError,OSError):pass
                incomplete=list((cache/'blobs').glob('*.incomplete')) if (cache/'blobs').exists() else []
                try:received=max((file.stat().st_size for file in incomplete),default=0)
                except OSError:continue
                progress(min(.15,.15*received/expected),'Downloading speech model')
        watcher=threading.Thread(target=model_progress,daemon=True)
        watcher.start()
        try:model = WhisperModel(model_name, device='cpu', compute_type='int8', cpu_threads=4, download_root=str(model_root))
        finally:stop.set()
        if progress:progress(.15,'Recognizing speech')
        def recognize(chosen):
            segments, details = model.transcribe(
                str(audio), language=chosen, task='translate' if output!='original' else 'transcribe',
                beam_size=3, vad_filter=True, word_timestamps=True,
                repetition_penalty=1.1, no_repeat_ngram_size=3,
                condition_on_previous_text=False,
                initial_prompt=None,
            )
            pieces=[]
            for segment in segments:
                pieces.append(segment)
                if progress:progress(min(.80,.15+.65*segment.end/max(.1,end-start)),'Recognizing speech')
            return pieces, details

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
        if output=='original' and language == 'auto' and info.language == 'hi' and quality(pieces) < -1:
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
        if output not in ('original','en'):
            captions=translate_captions(captions,output,progress)
        return {'language': info.language, 'captionLanguage':info.language if output=='original' else output,
                'confidence': confidence, 'segments': captions}
