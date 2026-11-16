from PIL import Image, ImageDraw, ImageFont
im=Image.new('RGB',(1400,1400),(24,32,48)); d=ImageDraw.Draw(im)
f=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',150); g=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',70)
d.ellipse((450,250,950,750),fill=(244,170,80))
d.text((700,950),"Morgen-",font=f,fill='white',anchor='mm'); d.text((700,1110),"Briefing",font=f,fill='white',anchor='mm'); d.text((700,1270),"für Anton",font=g,fill=(200,210,225),anchor='mm')
im.save('cover.png')
