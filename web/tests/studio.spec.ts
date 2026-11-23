import {test,expect} from "@playwright/test";

test("login, create project, open editor, render, and save settings",async({page})=>{
  let signedIn=false,projectCreated=false,rendered=false,editedStart=10,model="base";
  await page.route("**/api/**",async route=>{
    const req=route.request(),path=new URL(req.url()).pathname,method=req.method();
    const json=(data:unknown,status=200)=>route.fulfill({json:data,status});
    if(path==="/api/login"){signedIn=true;return json({ok:true})}
    if(!signedIn)return json({error:"Sign in"},401);
    if(path==="/api/state")return json({projects:projectCreated?[{id:1,title:"Playback test",url:"https://www.youtube.com/watch?v=abcdefghijk",chunks:[{id:2,hour:1,status:"ready",duration:100,sourceAvailable:true,highlights:[{id:3,start:editedStart,end:52,title:"Quiet comeback",status:"ready",sourceAvailable:true,preview:"/api/media/3/preview",clip:rendered?"/api/media/3/clip":null}]}]}]:[]});
    if(path==="/api/projects"){projectCreated=true;return json({id:1})}
    if(path==="/api/highlights/3/edit"){
      if(method==="PATCH"){editedStart=req.postDataJSON().start;return json({ok:true})}
      return json({start:editedStart,end:52,sourceDuration:100,edit:{layoutMode:"split",facePosition:"bottom",gameBox:[0,0,1,1],facecamBox:[.65,.05,.3,.35],facecamFraction:.5,captionMode:"off"}});
    }
    if(path==="/api/highlights/3/layout")return json({box:[.65,.05,.3,.35]});
    if(path==="/api/highlights/3/captions")return json({segments:[],job:{status:"idle"}});
    if(path==="/api/highlights/3/waveform")return json({samples:Array(100).fill(.2)});
    if(path==="/api/highlights/3/render"){rendered=true;return json({ok:true})}
    if(path==="/api/settings"){if(method==="PUT")model=req.postDataJSON().model;return json({model,maxDataGB:12})}
    return json({});
  });
  await page.goto("/");
  await page.getByLabel("Workspace password").fill("fixture-only");
  await page.getByRole("button",{name:"Enter studio"}).click();
  await page.getByLabel("Stream URL").fill("https://www.youtube.com/watch?v=abcdefghijk");
  await page.getByRole("button",{name:"Scan stream"}).click();
  await expect(page.getByRole("heading",{name:"Playback test"})).toBeVisible();
  await page.getByRole("link",{name:"Edit Quiet comeback"}).click();
  await expect(page.getByText("Timeline",{exact:true})).toBeVisible();
  await page.getByLabel("Start time").fill("00:12");
  await page.getByLabel("Start time").blur();
  await expect(page.getByLabel("Start time")).toHaveValue("00:12");
  await page.getByRole("link",{name:/Back to project/}).click();
  await page.getByLabel("Select clip").check();
  await page.getByRole("button",{name:"Render selected"}).click();
  await page.getByRole("link",{name:/Clips/}).click();
  await expect(page.getByRole("link",{name:"Download Quiet comeback"})).toBeVisible();
  await page.getByRole("link",{name:/Settings/}).click();
  await page.getByLabel("Highlight audio scan model").selectOption("small");
  await page.getByRole("button",{name:"Save settings"}).click();
  await expect.poll(()=>model).toBe("small");
});
