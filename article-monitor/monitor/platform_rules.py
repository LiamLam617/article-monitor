"""
Platform-specific extraction rules for article read counts.
Kept separate from core config to keep configuration focused.
"""

PLATFORM_EXTRACTORS = {
    'juejin': {
        'wait_for': 'css:.views-count',
        'timeout': 30000,
        'delay_before_return': 5000,
        'js_extract': True,
        'patterns': [
            r'JUEJIN_VIEWS_COUNT:([\d,]+)',
            r'class="views-count"[^>]*>\s*([\d,]+)\s*</span>',
            r'class="views-count"[^>]*>([^<\s]+)',
            r'class="views-count"[^>]*>([^<]+)',
            r'([\d,]+[km]?)\s*阅读',
        ],
        'parse_method': 'number_with_suffix',
    },
    'csdn': {
        'wait_for': 'css:.read-count',
        'patterns': [
            r'class="read-count"[^>]*>([^<]+)',
            r'阅读[：:]\s*([\d,]+[kmwKMW]?)',
            r'([\d,]+[kmwKMW]?)\s*阅读',
        ],
        'parse_method': 'number_with_suffix',
    },
    'cnblog': {
        'wait_for': 'css:#post_view_count',
        'patterns': [
            r'id="post_view_count"[^>]*>([\d,]+)</span>',
            r'id="post_view_count"[^>]*>([\d,]+)',
            r'阅读[：:]\s*([\d,]+)',
            r'views[：:]\s*([\d,]+)',
        ],
        'parse_method': 'number',
    },
    '51cto': {
        'timeout': 30000,
        'patterns': [
            r'<em[^>]*>阅读数</em>\s*<b[^>]*>([\d,]+)</b>',
            r'阅读数</em>\s*<b[^>]*>([\d,]+)</b>',
            r'阅读数[：:]\s*([\d,]+)',
            r'<p[^>]*class="[^"]*mess-tag[^"]*"[^>]*>.*?<b[^>]*>([\d,]+)</b>',
        ],
        'parse_method': 'number',
    },
    'segmentfault': {
        'patterns': [
            r'<span[^>]*>阅读\s*<!--[^>]*-->\s*([\d,]+)</span>',
            r'阅读\s+([\d,]+)',
        ],
        'parse_method': 'number',
    },
    'jinshu': {
        'wait_for': 'css:span',
        'patterns': [
            r'<span[^>]*>阅读\s+([\d,]+)</span>',
            r'<span>阅读\s+([\d,]+)</span>',
            r'阅读\s+([\d,]+)',
            r'阅读\s*([\d,]+)',
        ],
        'parse_method': 'number',
    },
    'elecfans': {
        'patterns': [
            r'<span[^>]*class="art_click_count"[^>]*>([\d,]+)</span>',
            r'([\d,]+)\s*次阅读',
        ],
        'parse_method': 'number',
    },
    'MBB': {
        'timeout': 30000,
        'wait_for': 'css:.category.category-en',
        'patterns': [
            r'<span[^>]*class="[^"]*category[^"]*category-en[^"]*"[^>]*>.*?<span[^>]*class="[^"]*iconfont[^"]*browse-icon[^"]*"[^>]*>.*?</span>\s+([\d,]+)\s*</span>',
            r'<span[^>]*class="[^"]*category[^"]*category-en[^"]*"[^>]*>.*?<span[^>]*class="[^"]*iconfont[^"]*"[^>]*>.*?</span>\s+([\d,]+)\s*</span>(?!\s*<span[^>]*class="[^"]*category[^"]*category-en)',
            r'<span[^>]*class="[^"]*category[^"]*category-en[^"]*"[^>]*>.*?<span[^>]*>.*?</span>\s+([\d,]+)\s*</span>',
            r'<span[^>]*class="[^"]*view[^"]*"[^>]*>([\d,]+)</span>',
            r'阅读\s*([\d,]+)',
            r'浏览\s*([\d,]+)',
            r'([\d,]+)\s*阅读',
        ],
        'parse_method': 'number',
    },
    'eefocus': {
        'patterns': [
            r'<div[^>]*class="hot-num"[^>]*>.*?<img[^>]*>([\d,]+)</div>',
            r'class="hot-num"[^>]*>.*?([\d,]+)',
            r'([\d,]+)\s*次?阅读',
        ],
        'parse_method': 'number',
    },
    'sohu': {
        'wait_for': 'js:() => { const el = document.querySelector("em[data-role=\\"pv\\"]"); return el && /^\\d+$/.test(el.textContent.trim()); }',
        'timeout': 30000,
        'js_extract': True,
        'patterns': [
            r'SOHU_PV_COUNT:(\d+)',
            r'阅读\s*\(\s*(\d+)\s*\)',
            r'>(\d+)</em>',
        ],
        'parse_method': 'number',
    },
    'generic': {
        'patterns': [
            r'阅读[：:]\s*([\d,]+[kmw]?)',
            r'views[：:]\s*([\d,]+[kmw]?)',
            r'阅读数[：:]\s*([\d,]+[kmw]?)',
            r'([\d,]+[kmw]?)\s*阅读',
            r'([\d,]+[kmw]?)\s*views',
        ],
        'parse_method': 'number_with_suffix',
    },
}

