import json
import subprocess
import concurrent.futures

with open('out/robots.json', 'r', encoding='utf-8') as f:
    robots = json.load(f)

site = 'https://www.mayoclinic.org/'

def run_s(args, inp, outf):
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    o, e = p.communicate(input=json.dumps(inp).encode('utf-8') if inp is not None else None)
    with open(outf, 'wb') as f:
        f.write(o)
    return outf, p.returncode

tasks = [
    (['python', 'skills/crawl-access-audit/scripts/fetch_dual_identity.py'], {'url': site, 'robots': robots}, 'out/dual_homepage.json'),
    (['python', 'skills/crawl-access-audit/scripts/check_sitemap.py'], {'site': site, 'url': site, 'robots': robots}, 'out/sitemap.json'),
    (['python', 'skills/crawl-access-audit/scripts/check_crawl_depth.py'], {'site': site, 'robots': robots}, 'out/crawl_depth.json'),
    (['python', 'skills/crawl-access-audit/scripts/check_tls.py'], {'url': site}, 'out/tls.json')
]

if __name__ == '__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(run_s, *t) for t in tasks]
        for f in concurrent.futures.as_completed(futures):
            print(f.result())
