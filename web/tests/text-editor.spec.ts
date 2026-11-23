import {test,expect} from "@playwright/test";

test("timed text appears in preview and autosaves to the edit",async({page})=>{
  let saved:any=null;
  await page.route("**/api/**",async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    const json=(data:unknown)=>route.fulfill({json:data});
    if(path==="/api/state")return json({projects:[{id:1,title:"Text test",url:"https://www.youtube.com/watch?v=abcdefghijk",chunks:[{id:2,hour:1,status:"ready",duration:100,sourceAvailable:true,highlights:[{id:3,start:10,end:50,title:"Moment",status:"ready",sourceAvailable:true,preview:"/api/media/3/preview"}]}]}]});
    if(path==="/api/highlights/3/edit"){
      if(request.method()==="PATCH"){saved=request.postDataJSON();return json({ok:true})}
      return json({start:10,end:50,sourceDuration:100,edit:{layoutMode:"split",facePosition:"bottom",gameBox:[0,0,1,1],facecamBox:[.65,.05,.3,.35],facecamFraction:.5,captionTemplate:"solid",captionMode:"off",captionLanguage:"auto",captionOutput:"original",font:"Arial Bold.ttf",fontSize:43,textColor:"#ffffff",boxColor:"#000000",textOverlays:[]}});
    }
    if(path==="/api/highlights/3/layout")return json({box:[.65,.05,.3,.35]});
    if(path==="/api/highlights/3/captions")return json({segments:[],job:{status:"idle"}});
    if(path==="/api/highlights/3/waveform")return json({samples:Array(100).fill(.2)});
    return json({});
  });
  await page.goto("/edit/3");
  await page.getByRole("button",{name:"Text",exact:true}).click();
  await page.getByRole("button",{name:/Add text at playhead/}).click();
  await page.locator('.textOverlayCard input[maxlength="80"]').fill("WIN NOW");
  await expect(page.locator(".liveTextOverlay")).toHaveText("WIN NOW");
  await expect(page.locator(".textTrack button")).toHaveText("WIN NOW");
  await expect.poll(()=>saved?.edit?.textOverlays?.[0]?.text,{timeout:8000}).toBe("WIN NOW");
  expect(saved.edit.textOverlays[0]).toMatchObject({start:10,end:14,x:.5,y:.24});
});
