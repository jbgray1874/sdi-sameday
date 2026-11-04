import re, sys
sys.path.insert(0, ".")
import pdf_pack as p
for s in ["1.5 metres high, 900 wide, 500 deep", "1.5 m high 900 wide 500 deep", "1500 high 900 wide 500 deep",
          "about 1.5m high, 900mm wide, 500mm deep", "2 metres high, 1 metre wide, 40cm deep"]:
    print(repr(s), "->", p.parse_size(s))
