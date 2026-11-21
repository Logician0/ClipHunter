import {test,expect} from "@playwright/test";
test("login, create, trim, render and change settings",async({page})=>{
  let signedIn=false,projectCreated=false,rendered=false,start=10,model="base",mode="auto";
  await page.route("**/api/**", async route=>{
    const req=route.request(), path=new URL(req.url()).pathname, method=req.method();
    const json=(data:unknown,status=200)=>route.fulfill({json:data,status});
    if(path==="/api/login"){signedIn=true;return json({ok:true})}
    if(!signedIn)return json({error:"Sign in"},401);
    if(path==="/api/state")return json({projects:projectCreated?[{id:1,title:"Playback test",url:"https://www.youtube.com/watch?v=fixture",isLive:true,recording:true,chunks:[{id:2,hour:1,status:"ready",highlights:[{id:3,start,end:52,title:"Quiet comeback",status:"ready",clip:rendered?"/api/media/3/clip":null}]}]}]:[]});
    if(path==="/api/projects"){projectCreated=true;return json({id:1})}
    if(path==="/api/highlights/3"){start=req.postDataJSON().start;return json({ok:true})}
    if(path==="/api/highlights/3/render"){rendered=true;return json({ok:true})}
    if(path==="/api/settings"){if(method==="PUT")model=req.postDataJSON().model;return json({model,maxDataGB:12})}
    if(path==="/api/chunks/2/layout"){if(method==="PATCH")mode=req.postDataJSON().mode;return json({mode,box:null})}
    return json({});
  });
  await page.goto("/");
  await page.getByLabel("Workspace password").fill("fixture-only");
  await page.getByRole("button",{name:"Enter studio"}).click();
  await page.getByLabel("Stream URL").fill("https://www.youtube.com/watch?v=fixture");
  await page.getByRole("button",{name:"Scan stream"}).click();
  await expect(page.getByRole("heading",{name:"Playback test"})).toBeVisible();
  await expect(page.getByRole("button",{name:"Stop recording"})).toBeVisible();
  await page.getByRole("button",{name:"Edit layout"}).click();
  await page.getByLabel("Vertical layout").selectOption("full");
  await page.getByRole("button",{name:"Save layout"}).click();
  await expect.poll(()=>mode).toBe("full");
  await page.getByText("Trim clip",{exact:true}).click();
  await page.getByLabel("Start in hour (s)").fill("12");
  await page.getByRole("button",{name:"Save trim"}).click();
  await expect.poll(()=>start).toBe(12);
  await page.getByLabel("Select clip").check();
  await page.getByRole("button",{name:"Render selected"}).click();
  await page.getByRole("link",{name:"Open clips"}).click();
  await expect(page.getByRole("link",{name:"Download MP4"})).toBeVisible();
  await page.getByRole("link",{name:"Settings"}).click();
  await page.getByLabel("Transcription model").selectOption("small");
  await page.getByRole("button",{name:"Save settings"}).click();
  await expect(page.getByRole("status")).toHaveText("Saved");
  expect(model).toBe("small");
});
