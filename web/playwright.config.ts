import {defineConfig} from "@playwright/test";
export default defineConfig({
  testDir:"./tests",
  use:{baseURL:"http://127.0.0.1:3110",channel:"chrome",viewport:{width:1280,height:900}},
  webServer:{command:"npm start -- -p 3110",url:"http://127.0.0.1:3110",reuseExistingServer:false}
});
