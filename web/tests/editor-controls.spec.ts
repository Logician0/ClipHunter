import {test,expect} from "@playwright/test";

test("caption timeline opens its text editor and exports stay visible",async({page})=>{
  let saved:any=null;
  await page.route("**/api/**",async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    const json=(data:unknown)=>route.fulfill({json:data});
    if(path==="/api/state")return json({projects:[{id:1,title:"Test",url:"https://www.youtube.com/watch?v=abcdefghijk",chunks:[{id:2,hour:1,status:"ready",duration:100,sourceAvailable:true,highlights:[{id:3,start:10,end:50,title:"Moment",status:"ready",sourceAvailable:true,preview:"/api/media/3/preview"}]}]}]});
    if(path==="/api/highlights/3/edit"){
      if(request.method()==="PATCH"){saved=request.postDataJSON();return json({ok:true})}
      return json({start:10,end:50,sourceDuration:100,edit:{layoutMode:"split",facePosition:"bottom",gameBox:[0,0,1,1],facecamBox:[.65,.05,.3,.35],facecamFraction:.5,captionTemplate:"solid",captionMode:"auto",captionLanguage:"auto",captionOutput:"original",font:"Arial Bold.ttf",fontSize:43,textColor:"#ffffff",boxColor:"#000000",textOverlays:[]}});
    }
    if(path==="/api/highlights/3/layout")return json({box:[.65,.05,.3,.35]});
    if(path==="/api/highlights/3/captions")return json({segments:[{start:12,end:16,text:"First line"}],job:{status:"idle"}});
    if(path==="/api/highlights/3/waveform")return json({samples:Array(100).fill(.2)});
    if(path==="/api/highlights/3/audio")return json({present:false,bytes:0});
    return json({});
  });
  await page.goto("/edit/3");
  await page.getByRole("button",{name:/Edit caption 1/}).click();
  await expect(page.getByLabel("Caption 1 text")).toBeVisible();
  await page.getByLabel("Caption 1 text").fill("Edited line");
  await expect.poll(()=>saved?.edit?.captionMode,{timeout:8000}).toBe("auto");
  const block=page.getByRole("button",{name:/Edit caption 1/});
  const rect=await block.boundingBox();
  expect(rect).not.toBeNull();
  await page.mouse.move(rect!.x+rect!.width-2,rect!.y+rect!.height/2);
  await page.mouse.down();
  await page.mouse.move(rect!.x+rect!.width+14,rect!.y+rect!.height/2,{steps:4});
  await page.mouse.up();
  await expect(page.getByLabel("Caption 1 end")).not.toHaveValue("00:16.0");
  await expect(page.getByRole("button",{name:"Export 1080×1920"})).toBeVisible();
  await page.getByRole("button",{name:"Audio",exact:true}).click();
  await expect(page.getByText("Sound mix")).toBeVisible();
  const pageHeight=await page.evaluate(()=>document.documentElement.scrollHeight);
  expect(pageHeight).toBeLessThanOrEqual(page.viewportSize()!.height+2);
});
