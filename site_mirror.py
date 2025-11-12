import os
import requests
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from pathlib import Path
import time
import sys

class RobustSiteScraper:
    def __init__(self, base_url, output_dir="./scraped_site", delay=1, max_depth=10):
        self.base_url = base_url.rstrip('/')
        self.output_dir = Path(output_dir)
        self.delay = delay
        self.max_depth = max_depth

        self.visited_urls = set()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def is_same_domain(self, url):
        """检查是否同一域名"""
        try:
            return urlparse(url).netloc == urlparse(self.base_url).netloc
        except:
            return False

    def normalize_url(self, url):
        """标准化URL，处理异常情况"""
        try:
            # 移除重复的协议和非法字符
            url = re.sub(r'([a-zA-Z]+:/+)+', r'\1', url)
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" + (f"?{parsed.query}" if parsed.query else "")
        except Exception as e:
            print(f"URL标准化失败: {url}, 错误: {e}")
            return None

    def get_file_path(self, url):
        """根据URL生成本地文件路径"""
        try:
            parsed = urlparse(url)
            path = parsed.path

            if not path or path == '/':
                return self.output_dir / 'index.html'

            # 移除开头的斜杠
            if path.startswith('/'):
                path = path[1:]

            # 清理路径中的特殊字符
            path = re.sub(r'[<>:"|?*]', '_', path)

            # 限制路径长度
            if len(path) > 200:
                # 如果路径太长，使用哈希值
                import hashlib
                hash_obj = hashlib.md5(path.encode())
                extension = os.path.splitext(path)[1] or '.html'
                path = f"long_path_{hash_obj.hexdigest()}{extension}"

            # 如果没有扩展名，根据内容猜测
            if '.' not in os.path.basename(path):
                if path.endswith('/'):
                    path = path + 'index.html'
                else:
                    # 根据常见路径猜测文件类型
                    if any(keyword in url.lower() for keyword in ['/css/', '.css']):
                        path = path + '.css'
                    elif any(keyword in url.lower() for keyword in ['/js/', '.js']):
                        path = path + '.js'
                    elif any(keyword in url.lower() for keyword in ['/images/', '/img/', '.jpg', '.png', '.gif']):
                        path = path + '.jpg'  # 默认图片扩展名
                    else:
                        path = path + '/index.html'

            full_path = self.output_dir / path

            # 创建目录
            full_path.parent.mkdir(parents=True, exist_ok=True)

            return full_path

        except Exception as e:
            print(f"生成文件路径失败: {url}, 错误: {e}")
            # 返回一个安全的默认路径
            return self.output_dir / 'error_files' / 'default.html'

    def download_file(self, url, file_path):
        """下载文件"""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            # 保存文件
            with open(file_path, 'wb') as f:
                f.write(response.content)

            print(f"✓ 下载成功: {url}")
            return response.content

        except Exception as e:
            print(f"✗ 下载失败 {url}: {e}")
            return None

    def extract_css_urls(self, css_content, base_url):
        """从CSS内容中安全地提取URL"""
        urls = set()

        try:
            # 匹配各种CSS URL模式
            patterns = [
                r'url\([\'"]?(.*?)[\'"]?\)',
                r'@import\s+[\'"]?(.*?)[\'"]?',
                r'src:\s*url\([\'"]?(.*?)[\'"]?\)'
            ]

            for pattern in patterns:
                matches = re.findall(pattern, css_content, re.IGNORECASE)
                for match in matches:
                    if match and not match.startswith(('data:', '#', 'javascript:')):
                        # 清理URL
                        clean_url = match.split('?')[0].split('#')[0].strip()
                        if clean_url:
                            absolute_url = urljoin(base_url, clean_url)
                            normalized_url = self.normalize_url(absolute_url)
                            if normalized_url and self.is_same_domain(normalized_url):
                                urls.add(normalized_url)

        except Exception as e:
            print(f"提取CSS URL失败: {e}")

        return urls

    def extract_html_links(self, soup, base_url):
        """从HTML中安全地提取链接"""
        urls = set()

        try:
            # HTML标签中的链接
            tags_to_check = [
                ('a', 'href'),
                ('link', 'href'),
                ('script', 'src'),
                ('img', 'src'),
                ('source', 'src'),
                ('iframe', 'src')
            ]

            for tag, attr in tags_to_check:
                for element in soup.find_all(tag, {attr: True}):
                    link = element[attr]
                    if link and not link.startswith(('javascript:', 'mailto:', 'tel:', '#', 'data:')):
                        absolute_url = urljoin(base_url, link)
                        normalized_url = self.normalize_url(absolute_url)
                        if normalized_url and self.is_same_domain(normalized_url):
                            urls.add(normalized_url)

        except Exception as e:
            print(f"提取HTML链接失败: {e}")

        return urls

    def extract_all_links(self, content, base_url, content_type=""):
        """从内容中提取所有链接"""
        all_links = set()

        try:
            if isinstance(content, bytes):
                try:
                    content_str = content.decode('utf-8')
                except:
                    content_str = content.decode('latin-1', errors='ignore')
            else:
                content_str = str(content)

            # 如果是CSS文件
            if content_type and 'css' in content_type or base_url.endswith('.css'):
                css_links = self.extract_css_urls(content_str, base_url)
                all_links.update(css_links)

            # 如果是HTML文件
            elif content_type and 'html' in content_type or base_url.endswith(('.html', '.htm', '/')):
                soup = BeautifulSoup(content_str, 'html.parser')
                html_links = self.extract_html_links(soup, base_url)
                all_links.update(html_links)

                # 从style属性中提取
                for element in soup.find_all(style=True):
                    style_content = element['style']
                    style_links = self.extract_css_urls(style_content, base_url)
                    all_links.update(style_links)

            # 总是从内容中提取CSS URL（备用方法）
            css_pattern = r'url\([\'"]?([^\)\'\"]*?)[\'"]?\)'
            css_matches = re.findall(css_pattern, content_str)
            for match in css_matches:
                if match and not match.startswith(('data:', '#')):
                    absolute_url = urljoin(base_url, match)
                    normalized_url = self.normalize_url(absolute_url)
                    if normalized_url and self.is_same_domain(normalized_url):
                        all_links.add(normalized_url)

        except Exception as e:
            print(f"提取链接失败: {e}")

        return all_links

    def process_url(self, url, depth=0):
        """处理单个URL，带深度限制"""
        if depth > self.max_depth:
            print(f"达到最大深度限制: {url}")
            return

        if url in self.visited_urls:
            return

        self.visited_urls.add(url)
        print(f"处理 [{depth}]: {url}")

        # 下载文件
        file_path = self.get_file_path(url)
        content = self.download_file(url, file_path)

        if content is None:
            return

        # 获取内容类型
        content_type = ""
        try:
            head_response = self.session.head(url, timeout=10)
            content_type = head_response.headers.get('content-type', '').lower()
        except:
            pass

        # 提取所有链接
        links = self.extract_all_links(content, url, content_type)

        # 处理新发现的链接
        for link in links:
            if link not in self.visited_urls:
                self.process_url(link, depth + 1)

        time.sleep(self.delay)

    def crawl(self):
        """开始爬取"""
        print(f"开始爬取: {self.base_url}")
        print(f"输出目录: {self.output_dir}")
        print(f"最大深度: {self.max_depth}")
        print("-" * 50)

        try:
            self.process_url(self.base_url, 0)
        except RecursionError:
            print("递归深度过大，停止爬取")
        except KeyboardInterrupt:
            print("\n用户中断爬取")
        except Exception as e:
            print(f"爬取过程中发生错误: {e}")

        print("-" * 50)
        print(f"爬取完成! 共处理 {len(self.visited_urls)} 个资源")

def main():
    print("稳定版整站爬取工具")
    print("=" * 50)

    url = input("请输入要爬取的网站URL: ").strip()
    if not url:
        print("URL不能为空!")
        return

    output_dir = input("请输入输出目录 (默认: ./scraped_site): ").strip()
    if not output_dir:
        output_dir = "./scraped_site"

    # 设置递归深度限制
    sys.setrecursionlimit(1000)

    # 创建爬虫并开始爬取
    scraper = RobustSiteScraper(url, output_dir, max_depth=20)
    scraper.crawl()

if __name__ == "__main__":
    main()
