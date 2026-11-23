"""Export editable, absolute source-time caption lines as clip-relative SRT."""


def _stamp(seconds):
    milliseconds=round(max(0,seconds)*1000)
    hours,rest=divmod(milliseconds,3_600_000)
    minutes,rest=divmod(rest,60_000)
    whole,millis=divmod(rest,1000)
    return f'{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}'


def render_srt(segments,start,end):
    lines=[]
    for item in sorted(segments,key=lambda part:part['start']):
        left=max(start,float(item['start']))
        right=min(end,float(item['end']))
        if right<=left or not item.get('text','').strip():continue
        content=item['text'].replace('\r\n','\n').replace('\r','\n').strip()
        lines.append(f'{len(lines)+1}\n{_stamp(left-start)} --> {_stamp(right-start)}\n{content}\n')
    return '\n'.join(lines)+'\n' if lines else ''
