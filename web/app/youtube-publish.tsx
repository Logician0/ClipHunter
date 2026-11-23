"use client";
import Link from "next/link";
import {useEffect,useState} from "react";

type RequestFn=(path:string,method?:string,body?:unknown)=>Promise<any>;
type Channel={configured:boolean;connected:boolean;channel?:{id:string;title:string}};
type Upload={id?:number;status:string;progress?:number;bytes_sent?:number;total_bytes?:number;eta_seconds?:number;video_id?:string;error?:string};
const size=(bytes:number)=>bytes>=1048576?`${(bytes/1048576).toFixed(1)} MB`:`${Math.round(bytes/1024)} KB`;
export default function YoutubePublish({id,api}:{id:string;api:RequestFn}){
  const [channel,setChannel]=useState<Channel|null>(null),[upload,setUpload]=useState<Upload>({status:"idle"});
  const [title,setTitle]=useState(""),[description,setDescription]=useState(""),[tags,setTags]=useState("");
  const [privacy,setPrivacy]=useState("private"),[schedule,setSchedule]=useState(""),[madeForKids,setMadeForKids]=useState<"yes"|"no"|"">("");
  const [busy,setBusy]=useState(false),[message,setMessage]=useState("");
  useEffect(()=>{let active=true;Promise.all([api('/youtube/channel'),api(`/youtube/highlights/${id}/defaults`),api(`/youtube/highlights/${id}/upload`)]).then(([connected,defaults,job])=>{
    if(!active)return;setChannel(connected);setTitle(defaults.title);setDescription(defaults.description);setTags(defaults.tags.join(', '));setUpload(job);
  }).catch(e=>{if(active)setMessage(e.message)});return()=>{active=false}},[api,id]);
  useEffect(()=>{if(!['queued','uploading'].includes(upload.status))return;const timer=setInterval(()=>void api(`/youtube/highlights/${id}/upload`).then(setUpload).catch(e=>setMessage(e.message)),2000);return()=>clearInterval(timer)},[api,id,upload.status]);
  const submit=async()=>{
    if(!channel?.connected){setMessage('Connect a YouTube channel in Settings first.');return}
    if(!madeForKids){setMessage('Choose whether this video is made for kids.');return}
    let publishAt:string|undefined;
    if(privacy==='schedule'){
      if(!schedule){setMessage('Choose a schedule date and time.');return}
      const date=new Date(schedule);
      if(Number.isNaN(date.getTime())){setMessage('Choose a valid schedule date and time.');return}
      publishAt=date.toISOString();
    }
    setBusy(true);setMessage('');
    try{
      const payload={title,description,tags:tags.split(',').map(x=>x.trim()).filter(Boolean),privacy,publishAt,madeForKids:madeForKids==='yes'};
      await api(`/youtube/highlights/${id}/upload`,'POST',payload);
      setUpload(await api(`/youtube/highlights/${id}/upload`));
      setMessage(privacy==='schedule'?'Uploading privately for scheduled publication…':'Uploading to YouTube…');
    }catch(e){setMessage((e as Error).message)}finally{setBusy(false)}
  };
  return <section className="youtubePublish"><div className="editorSectionHeading"><div><span className="small">04 / PUBLISH</span><h2>YouTube upload</h2></div></div>
    {!channel?<p>Checking channel…</p>:!channel.connected?<p>Connect a channel in <Link href="/settings">Settings</Link> to upload or schedule this clip.</p>:<>
      <div className="publishChannel"><span>Destination channel</span><strong>{channel.channel?.title||'Connected channel'}</strong><small>{channel.channel?.id}</small></div>
      <label>Video title<input value={title} maxLength={100} onChange={e=>setTitle(e.target.value)}/></label>
      <label>Description<textarea value={description} maxLength={5000} rows={5} onChange={e=>setDescription(e.target.value)}/></label>
      <label>Tags <small>Separate with commas</small><input value={tags} onChange={e=>setTags(e.target.value)}/></label>
      <label>Visibility<select value={privacy} onChange={e=>setPrivacy(e.target.value)}><option value="private">Private now</option><option value="unlisted">Unlisted now</option><option value="public">Public now</option><option value="schedule">Schedule public release</option></select></label>
      {privacy==='schedule'&&<label>Publish date and time<input type="datetime-local" value={schedule} onChange={e=>setSchedule(e.target.value)}/></label>}
      <fieldset className="audienceChoice"><legend>Is this video made for kids?</legend><label><input type="radio" name={`kids-${id}`} checked={madeForKids==='no'} onChange={()=>setMadeForKids('no')}/> No</label><label><input type="radio" name={`kids-${id}`} checked={madeForKids==='yes'} onChange={()=>setMadeForKids('yes')}/> Yes</label></fieldset>
      <p className="captionHint">The finished MP4 includes captions only if you enabled them before export. Review the video and details before uploading.</p>
      <button className="primary" disabled={busy||['queued','uploading'].includes(upload.status)} onClick={()=>void submit()}>{busy?'Starting…':upload.status==='complete'?'Upload another copy':privacy==='schedule'?'Upload and schedule':privacy==='public'?'Publish public now':'Upload to YouTube'}</button>
    </>}
    {['queued','uploading'].includes(upload.status)&&<div className="processProgress" role="status"><div className="processTop"><strong>{upload.status==='queued'?'Waiting to upload':'Uploading to YouTube'}</strong><span>{Math.round((upload.progress||0)*100)}%</span></div><div className="processTrack"><span style={{width:`${(upload.progress||0)*100}%`}}/></div><small>{size(upload.bytes_sent||0)} / {size(upload.total_bytes||0)}{upload.eta_seconds!=null&&upload.eta_seconds>0?` · about ${Math.ceil(upload.eta_seconds/60)} min remaining`:''}</small></div>}
    {upload.status==='complete'&&upload.video_id&&<p className="uploadSuccess">Uploaded video: <a href={`https://www.youtube.com/watch?v=${encodeURIComponent(upload.video_id)}`} target="_blank" rel="noopener noreferrer">Open on YouTube ↗</a></p>}
    {upload.status==='error'&&<div className="uploadError"><p>{upload.error||'Upload failed.'}</p><button onClick={async()=>{try{await api(`/youtube/uploads/${upload.id}/retry`,'POST',{});setUpload(await api(`/youtube/highlights/${id}/upload`));setMessage('Retrying upload…')}catch(e){setMessage((e as Error).message)}}}>Retry upload</button></div>}
    <p role="status">{message}</p>
  </section>;
}
