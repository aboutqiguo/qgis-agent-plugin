import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import sys

BASE_URL = 'https://qgis.org/pyqgis/4.0/'
OUTPUT_DIR = 'pyqgis_4.0_docs'

visited = set()
to_visit = set([BASE_URL])

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def get_filename_from_url(url):
    parsed = urlparse(url)
    path = parsed.path
    if path.endswith('/'):
        path += 'index.html'
    
    # Extract the relative path part after /pyqgis/4.0/
    rel_path = path.split('/pyqgis/4.0/')[-1]
    if not rel_path:
        rel_path = 'index.html'
        
    # Convert to markdown filename
    md_name = rel_path.replace('.html', '.md').replace('/', '_')
    return os.path.join(OUTPUT_DIR, md_name)

def extract_text_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    # Find the main content area (Sphinx docs usually use div with class "document" or "body")
    main_content = soup.find('div', class_='document')
    if not main_content:
        main_content = soup.find('div', class_='body')
    if not main_content:
        main_content = soup.find('div', itemprop='articleBody')
    if not main_content:
        main_content = soup
        
    # Extract text with basic formatting
    lines = []
    for element in main_content.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'pre', 'li', 'dt', 'dd']):
        if element.name in ['h1', 'h2', 'h3', 'h4']:
            lines.append('\n' + '#' * int(element.name[1]) + ' ' + element.get_text(strip=True))
        elif element.name == 'pre':
            lines.append('\n```python\n' + element.get_text() + '\n```\n')
        elif element.name == 'dt':
            lines.append('\n**' + element.get_text(strip=True) + '**')
        elif element.name == 'dd':
            lines.append('  ' + element.get_text(strip=True))
        elif element.name == 'li':
            lines.append('- ' + element.get_text(strip=True))
        else:
            lines.append(element.get_text(strip=True))
            
    return '\n'.join(lines)

def crawl():
    print(f"Starting crawl of {BASE_URL}")
    session = requests.Session()
    
    count = 0
    # Limit to 500 pages for testing/sanity, PyQGIS API can be huge
    while to_visit and count < 1000:
        url = to_visit.pop()
        # Remove fragment if any
        url = url.split('#')[0]
        
        if url in visited:
            continue
            
        visited.add(url)
        print(f"[{count+1}] Fetching: {url}")
        
        try:
            response = session.get(url, timeout=10)
            if response.status_code != 200:
                continue
                
            html_content = response.text
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract and save content
            md_content = extract_text_from_html(html_content)
            filename = get_filename_from_url(url)
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(md_content)
                
            # Find all links
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                full_url = urljoin(url, href)
                full_url = full_url.split('#')[0]
                
                # Only follow links within the pyqgis/4.0 domain and not already visited
                if full_url.startswith(BASE_URL) and full_url not in visited and '_static' not in full_url:
                    if full_url.endswith('.html') or full_url.endswith('/'):
                        to_visit.add(full_url)
                        
            count += 1
            # Be nice to the server
            time.sleep(0.1)
            
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            
    print(f"Finished crawling. Crawled {count} pages.")

if __name__ == '__main__':
    crawl()
