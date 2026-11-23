"use client";
import {useEffect} from "react";
import YoutubePublish from "./youtube-publish";

type RequestFn=(path:string,method?:string,body?:unknown)=>Promise<any>;
export default function ClipPublishDialog({id,title,api,onClose}:{id:string;title:string;api:RequestFn;onClose:()=>void}){
  useEffect(()=>{const close=(event:KeyboardEvent)=>{if(event.key==="Escape")onClose()};window.addEventListener("keydown",close);return()=>window.removeEventListener("keydown",close)},[onClose]);
  return <div className="publishBackdrop" onPointerDown={event=>{if(event.target===event.currentTarget)onClose()}}>
    <section className="publishDialog" role="dialog" aria-modal="true" aria-label={`Publish ${title} to YouTube`}>
      <div className="publishDialogHead"><div><span className="small">PUBLISH CLIP</span><h2>{title}</h2></div><button aria-label="Close YouTube publisher" onClick={onClose}>✕</button></div>
      <YoutubePublish id={id} api={api}/>
    </section>
  </div>;
}
