import urllib.request
import re
try:
    req = urllib.request.Request('https://amurrio.eus/cas', headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')
    if 'Nonehttps' in html:
        print('FOUND Nonehttps IN HTML!')
    for match in re.findall(r'href=[\"\'\s]*(.*?facebook.*?)[\"\'\s]', html):
        print(match)
except Exception as e:
    print(e)
