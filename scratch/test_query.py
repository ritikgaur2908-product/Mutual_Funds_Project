import urllib.request
import json
import sys

# Configure UTF-8 output to prevent Windows console encoding crashes
sys.stdout.reconfigure(encoding='utf-8')

queries = [
    "What is the fund size of HDFC Defence Fund Direct Growth?",
    "What is the fund size of HDFC Mid Cap Fund Direct Growth?",
    "What is the fund size of HDFC Nifty 50 Index Fund?",
    "What is the fund size of HDFC Silver ETF FoF?",
    "What is the total AUM of HDFC Mutual Fund as a fund house?"
]

for q in queries:
    print(f"\n[*] Query: {q}")
    data = json.dumps({"message": q}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:8000/query",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode("utf-8"))
            print(f"  Answer: {res['answer']}")
            print(f"  Source: {res['source_url']}")
    except Exception as e:
        print(f"  Error: {e}")
