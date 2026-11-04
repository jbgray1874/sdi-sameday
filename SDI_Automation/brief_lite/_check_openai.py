"""Does the OpenAI key work, and which image models can it use? (Listing models costs nothing.)"""
from dotenv import load_dotenv
load_dotenv(r"C:\SDI_Automation\.env")
from openai import OpenAI
try:
    ids = sorted(m.id for m in OpenAI().models.list().data)
    print("key OK -", len(ids), "models")
    print("image models:", [i for i in ids if "image" in i or "dall" in i])
except Exception as e:
    print("key problem:", str(e)[:300])
