"""Send 0xD8 (hidden per-key colour). PROTOCOL 76.

    uv run --with hidapi python tools/setled.py <idx>:<r>,<g>,<b> [more...]
    uv run --with hidapi python tools/setled.py --range A B r g b     # indices A..B-1

Record = (index, R, G, B). Up to 14 LEDs per frame; auto-splits. Colour order
(which byte is R/G/B) is INFERRED, not confirmed - this is the test that confirms it.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nuphykit.device import Device

def send(dev, records):
    for i in range(0, len(records), 14):
        chunk = records[i:i+14]
        data = []
        for idx,r,g,b in chunk:
            data += [idx&0xFF, r&0xFF, g&0xFF, b&0xFF]
        payload = [len(data), 0, 0, 0] + data
        dev.send(0xD8, payload, wait=0.15)

def main():
    a = sys.argv[1:]
    recs=[]
    if a and a[0]=='--range':
        lo,hi,r,g,b = int(a[1]),int(a[2]),int(a[3],0),int(a[4],0),int(a[5],0)
        recs=[(i,r,g,b) for i in range(lo,hi)]
    else:
        for tok in a:
            idx,rgb = tok.split(':'); r,g,b = rgb.split(',')
            recs.append((int(idx,0),int(r,0),int(g,0),int(b,0)))
    with Device() as dev:
        send(dev, recs)
    print(f"sent 0xD8 for {len(recs)} LED(s)")

if __name__=='__main__':
    main()
