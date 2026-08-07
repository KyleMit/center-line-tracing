const {PNG}=require('pngjs');const fs=require('fs');
const [,,src,ox,oy,w,h,out]=process.argv;
const p=PNG.sync.read(fs.readFileSync(src));
const X=+ox,Y=+oy,W=Math.min(+w,p.width-X),H=Math.min(+h,p.height-Y);
const o=new PNG({width:W,height:H});
for(let y=0;y<H;y++) p.data.copy(o.data,y*W*4,((Y+y)*p.width+X)*4,((Y+y)*p.width+X+W)*4);
fs.writeFileSync(out,PNG.sync.write(o));
console.log(out,W,H);
