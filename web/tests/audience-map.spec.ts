import {test,expect} from "@playwright/test";

test("audience timeline selects a moment for a sparse clip",async({page})=>{
  let requested:number|null=null;
  await page.route("**/api/**",async route=>{
    const req=route.request(),path=new URL(req.url()).pathname;
    const json=(data:unknown,status=200)=>route.fulfill({json:data,status});
    if(path==="/api/state")return json({projects:[{id:1,title:"Audience test",url:"https://www.youtube.com/watch?v=abcdefghijk",chunks:[{id:2,hour:1,status:"ready",sparse:true,duration:60,scanMethod:"chat",highlights:[]}]}]});
    if(path==="/api/chunks/2/chat-heatmap")return json({binSeconds:15,duration:60,posts:[1,20,3,0],reactions:[0,8,0,0],viewerPosts:[1,18,3,0],status:"available"});
    if(path==="/api/chunks/2/manual-clip"){requested=req.postDataJSON().start;return json({ok:true},202)}
    return json({});
  });
  await page.goto("/p/1");
  await expect(page.getByText("Audience activity",{exact:true})).toBeVisible();
  await page.getByRole("button",{name:/00:00:15, 20 chat messages/}).click();
  await expect(page.getByLabel("Manual clip start")).toHaveValue("00:00:15");
  await page.getByRole("button",{name:"Prepare clip here"}).click();
  await expect.poll(()=>requested).toBe(15);
});
