-- =====================================================
-- PRESET TEMPLATES — Instagram Carousel + Newsletter
-- Run in Supabase SQL Editor after schema.sql
-- =====================================================

-- =====================================================
-- INSTAGRAM PRESET TEMPLATES
-- =====================================================

-- 1. Minimal Dark
INSERT INTO preset_templates (template_type, name, html_content, aspect_ratio, thumbnail_url) VALUES (
'instagram',
'Minimal Dark',
'<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url(''https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap'');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    width: 1080px; height: 1080px;
    background: linear-gradient(160deg, #0a0a0a 0%, #1a1a2e 50%, #0f0f1a 100%);
    font-family: ''Inter'', sans-serif;
    color: #ffffff;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 80px;
    overflow: hidden;
    position: relative;
  }
  .accent-line {
    position: absolute;
    top: 60px; left: 80px;
    width: 60px; height: 4px;
    background: #7c5ce7;
    border-radius: 2px;
  }
  .slide-content {
    font-size: 42px;
    line-height: 1.4;
    font-weight: 600;
    letter-spacing: -0.5px;
    max-width: 920px;
  }
  .slide-content strong {
    color: #a29bfe;
    font-weight: 800;
  }
  .footer {
    position: absolute;
    bottom: 60px; left: 80px; right: 80px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 20px;
    color: rgba(255,255,255,0.4);
  }
  .brand { font-weight: 700; color: rgba(255,255,255,0.6); }
  .page-num { font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
  <div class="accent-line"></div>
  <div class="slide-content">{{SLIDE_CONTENT}}</div>
  <div class="footer">
    <span class="brand">{{BRAND_NAME}}</span>
    <span class="page-num">{{SLIDE_NUM}} / {{TOTAL_SLIDES}}</span>
  </div>
</body>
</html>',
'1:1',
''
);

-- 2. Clean Light
INSERT INTO preset_templates (template_type, name, html_content, aspect_ratio, thumbnail_url) VALUES (
'instagram',
'Clean Light',
'<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url(''https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap'');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    width: 1080px; height: 1080px;
    background: #fafafa;
    font-family: ''Inter'', sans-serif;
    color: #1a1a1a;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 80px;
    overflow: hidden;
    position: relative;
  }
  .top-bar {
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 6px;
    background: linear-gradient(90deg, #3b82f6, #60a5fa);
  }
  .slide-content {
    font-size: 44px;
    line-height: 1.45;
    font-weight: 600;
    color: #1e293b;
    max-width: 920px;
  }
  .slide-content strong {
    color: #3b82f6;
    font-weight: 800;
  }
  .card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    padding: 50px 60px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.04);
  }
  .footer {
    position: absolute;
    bottom: 50px; left: 80px; right: 80px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 18px;
    color: #94a3b8;
  }
  .brand { font-weight: 700; color: #64748b; }
</style>
</head>
<body>
  <div class="top-bar"></div>
  <div class="card">
    <div class="slide-content">{{SLIDE_CONTENT}}</div>
  </div>
  <div class="footer">
    <span class="brand">{{BRAND_NAME}}</span>
    <span>{{SLIDE_NUM}} / {{TOTAL_SLIDES}}</span>
  </div>
</body>
</html>',
'1:1',
''
);

-- 3. Bold Gradient
INSERT INTO preset_templates (template_type, name, html_content, aspect_ratio, thumbnail_url) VALUES (
'instagram',
'Bold Gradient',
'<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url(''https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap'');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    width: 1080px; height: 1080px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    font-family: ''Inter'', sans-serif;
    color: #ffffff;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    padding: 80px;
    overflow: hidden;
    position: relative;
  }
  .bg-shape {
    position: absolute;
    width: 600px; height: 600px;
    border-radius: 50%;
    background: rgba(255,255,255,0.05);
    top: -100px; right: -150px;
  }
  .bg-shape-2 {
    position: absolute;
    width: 400px; height: 400px;
    border-radius: 50%;
    background: rgba(255,255,255,0.04);
    bottom: -80px; left: -100px;
  }
  .slide-content {
    font-size: 48px;
    line-height: 1.35;
    font-weight: 700;
    max-width: 880px;
    position: relative;
    z-index: 1;
  }
  .slide-content strong {
    font-weight: 900;
    text-decoration: underline;
    text-decoration-color: rgba(255,255,255,0.4);
    text-underline-offset: 6px;
  }
  .footer {
    position: absolute;
    bottom: 50px; left: 80px; right: 80px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 20px;
    color: rgba(255,255,255,0.6);
    z-index: 1;
  }
  .brand { font-weight: 700; }
</style>
</head>
<body>
  <div class="bg-shape"></div>
  <div class="bg-shape-2"></div>
  <div class="slide-content">{{SLIDE_CONTENT}}</div>
  <div class="footer">
    <span class="brand">{{BRAND_NAME}}</span>
    <span>{{SLIDE_NUM}} / {{TOTAL_SLIDES}}</span>
  </div>
</body>
</html>',
'1:1',
''
);

-- 4. Professional
INSERT INTO preset_templates (template_type, name, html_content, aspect_ratio, thumbnail_url) VALUES (
'instagram',
'Professional',
'<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url(''https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap'');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    width: 1080px; height: 1080px;
    background: #0f172a;
    font-family: ''Inter'', sans-serif;
    color: #ffffff;
    display: flex;
    flex-direction: column;
    padding: 0;
    overflow: hidden;
    position: relative;
  }
  .header-bar {
    background: linear-gradient(90deg, #0ea5e9, #06b6d4);
    padding: 30px 60px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .brand { font-size: 22px; font-weight: 700; }
  .page-num { font-size: 18px; opacity: 0.8; }
  .content-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 60px 70px;
  }
  .slide-content {
    font-size: 40px;
    line-height: 1.5;
    font-weight: 500;
    color: #e2e8f0;
  }
  .slide-content strong {
    color: #38bdf8;
    font-weight: 700;
  }
  .bottom-accent {
    height: 4px;
    background: linear-gradient(90deg, #0ea5e9, #06b6d4);
  }
</style>
</head>
<body>
  <div class="header-bar">
    <span class="brand">{{BRAND_NAME}}</span>
    <span class="page-num">{{SLIDE_NUM}} / {{TOTAL_SLIDES}}</span>
  </div>
  <div class="content-area">
    <div class="slide-content">{{SLIDE_CONTENT}}</div>
  </div>
  <div class="bottom-accent"></div>
</body>
</html>',
'1:1',
''
);

-- 5. Creative Pop
INSERT INTO preset_templates (template_type, name, html_content, aspect_ratio, thumbnail_url) VALUES (
'instagram',
'Creative Pop',
'<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url(''https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap'');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    width: 1080px; height: 1080px;
    background: #fffbeb;
    font-family: ''Inter'', sans-serif;
    color: #1c1917;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 80px;
    overflow: hidden;
    position: relative;
  }
  .deco-circle {
    position: absolute;
    width: 300px; height: 300px;
    border-radius: 50%;
    background: #fbbf24;
    opacity: 0.15;
    top: -60px; right: -40px;
  }
  .deco-circle-2 {
    position: absolute;
    width: 200px; height: 200px;
    border-radius: 50%;
    background: #f97316;
    opacity: 0.12;
    bottom: 80px; left: -30px;
  }
  .deco-square {
    position: absolute;
    width: 120px; height: 120px;
    background: #ef4444;
    opacity: 0.1;
    transform: rotate(15deg);
    bottom: -20px; right: 120px;
    border-radius: 20px;
  }
  .slide-content {
    font-size: 46px;
    line-height: 1.4;
    font-weight: 700;
    max-width: 920px;
    position: relative;
    z-index: 1;
  }
  .slide-content strong {
    color: #ea580c;
    font-weight: 900;
    background: linear-gradient(180deg, transparent 60%, rgba(251,191,36,0.3) 60%);
    padding: 0 4px;
  }
  .footer {
    position: absolute;
    bottom: 50px; left: 80px; right: 80px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 18px;
    color: #a8a29e;
    z-index: 1;
  }
  .brand {
    font-weight: 700;
    color: #78716c;
    background: #fef3c7;
    padding: 6px 16px;
    border-radius: 20px;
    font-size: 16px;
  }
</style>
</head>
<body>
  <div class="deco-circle"></div>
  <div class="deco-circle-2"></div>
  <div class="deco-square"></div>
  <div class="slide-content">{{SLIDE_CONTENT}}</div>
  <div class="footer">
    <span class="brand">{{BRAND_NAME}}</span>
    <span>{{SLIDE_NUM}} / {{TOTAL_SLIDES}}</span>
  </div>
</body>
</html>',
'1:1',
''
);

-- =====================================================
-- NEWSLETTER PRESET TEMPLATES
-- =====================================================

-- 1. Minimal
INSERT INTO preset_templates (template_type, name, html_content, aspect_ratio, thumbnail_url) VALUES (
'newsletter',
'Minimal',
'<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, ''Segoe UI'', Roboto, ''Helvetica Neue'', Arial, sans-serif;
    background-color: #f9fafb;
    color: #374151;
    line-height: 1.7;
  }
  .container {
    max-width: 600px;
    margin: 0 auto;
    background: #ffffff;
  }
  .header {
    padding: 40px 32px 24px;
    border-bottom: 1px solid #e5e7eb;
  }
  .header h1 {
    margin: 0;
    font-size: 28px;
    font-weight: 700;
    color: #111827;
    line-height: 1.3;
  }
  .section {
    padding: 28px 32px;
  }
  .section h2 {
    font-size: 20px;
    font-weight: 600;
    color: #1f2937;
    margin: 0 0 12px 0;
  }
  .section p {
    margin: 0 0 16px 0;
    font-size: 16px;
    color: #4b5563;
  }
  .divider {
    border: none;
    border-top: 1px solid #e5e7eb;
    margin: 0;
  }
  .exclusive {
    background: #f0f9ff;
    border-left: 4px solid #3b82f6;
    padding: 24px 32px;
  }
  .exclusive h2 {
    color: #1d4ed8;
  }
  .footer {
    padding: 24px 32px;
    text-align: center;
    font-size: 13px;
    color: #9ca3af;
    border-top: 1px solid #e5e7eb;
  }
  .footer a { color: #6b7280; }
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>{{NEWSLETTER_TITLE}}</h1>
    </div>
    <div class="section">
      {{SECTION_1}}
    </div>
    <hr class="divider">
    <div class="section">
      {{SECTION_2}}
    </div>
    <div class="exclusive">
      {{EXCLUSIVE_SECTION}}
    </div>
    <div class="footer">
      {{FOOTER}}
    </div>
  </div>
</body>
</html>',
'1:1',
''
);

-- 2. Magazine
INSERT INTO preset_templates (template_type, name, html_content, aspect_ratio, thumbnail_url) VALUES (
'newsletter',
'Magazine',
'<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {
    margin: 0; padding: 0;
    font-family: Georgia, ''Times New Roman'', serif;
    background-color: #f5f5f0;
    color: #2d2d2d;
    line-height: 1.8;
  }
  .container {
    max-width: 620px;
    margin: 0 auto;
    background: #ffffff;
    border: 1px solid #e8e8e0;
  }
  .masthead {
    padding: 36px 40px 20px;
    text-align: center;
    border-bottom: 3px double #2d2d2d;
  }
  .masthead h1 {
    margin: 0;
    font-size: 32px;
    font-weight: 700;
    color: #1a1a1a;
    letter-spacing: -0.5px;
    font-style: italic;
  }
  .section {
    padding: 32px 40px;
  }
  .section h2 {
    font-size: 22px;
    font-weight: 700;
    color: #1a1a1a;
    margin: 0 0 16px 0;
    padding-bottom: 8px;
    border-bottom: 1px solid #d4d4c8;
  }
  .section p {
    margin: 0 0 14px 0;
    font-size: 16px;
    color: #3d3d3d;
  }
  .divider-ornament {
    text-align: center;
    padding: 4px 0;
    font-size: 20px;
    color: #b8b8a8;
    letter-spacing: 12px;
  }
  .exclusive {
    margin: 0 40px;
    padding: 28px 32px;
    background: #faf8f0;
    border: 1px solid #e8e0c8;
    border-radius: 4px;
  }
  .exclusive h2 {
    color: #8b6914;
    border-bottom-color: #e8e0c8;
  }
  .footer {
    padding: 28px 40px;
    text-align: center;
    font-size: 13px;
    color: #999;
    border-top: 3px double #2d2d2d;
    margin-top: 20px;
    font-family: -apple-system, sans-serif;
  }
  .footer a { color: #666; }
</style>
</head>
<body>
  <div class="container">
    <div class="masthead">
      <h1>{{NEWSLETTER_TITLE}}</h1>
    </div>
    <div class="section">
      {{SECTION_1}}
    </div>
    <div class="divider-ornament">&#8226; &#8226; &#8226;</div>
    <div class="section">
      {{SECTION_2}}
    </div>
    <div class="exclusive">
      {{EXCLUSIVE_SECTION}}
    </div>
    <div class="footer">
      {{FOOTER}}
    </div>
  </div>
</body>
</html>',
'1:1',
''
);

-- 3. Corporate
INSERT INTO preset_templates (template_type, name, html_content, aspect_ratio, thumbnail_url) VALUES (
'newsletter',
'Corporate',
'<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, ''Segoe UI'', Roboto, ''Helvetica Neue'', Arial, sans-serif;
    background-color: #eef2f7;
    color: #334155;
    line-height: 1.7;
  }
  .container {
    max-width: 600px;
    margin: 0 auto;
    background: #ffffff;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
  }
  .brand-header {
    background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
    padding: 32px 36px;
  }
  .brand-header h1 {
    margin: 0;
    font-size: 26px;
    font-weight: 700;
    color: #ffffff;
    line-height: 1.3;
  }
  .brand-header .subtitle {
    margin: 8px 0 0;
    font-size: 14px;
    color: rgba(255,255,255,0.7);
  }
  .section {
    padding: 28px 36px;
  }
  .section h2 {
    font-size: 19px;
    font-weight: 600;
    color: #1e293b;
    margin: 0 0 12px 0;
  }
  .section p {
    margin: 0 0 14px 0;
    font-size: 15px;
    color: #475569;
  }
  .divider {
    border: none;
    border-top: 1px solid #e2e8f0;
    margin: 0 36px;
  }
  .exclusive {
    margin: 0 24px;
    padding: 24px 28px;
    background: linear-gradient(135deg, #eff6ff, #f0f9ff);
    border-radius: 8px;
    border: 1px solid #bfdbfe;
  }
  .exclusive h2 {
    color: #1d4ed8;
    font-size: 17px;
  }
  .footer {
    padding: 24px 36px;
    text-align: center;
    font-size: 12px;
    color: #94a3b8;
    background: #f8fafc;
    border-top: 1px solid #e2e8f0;
  }
  .footer a { color: #64748b; text-decoration: underline; }
</style>
</head>
<body>
  <div class="container">
    <div class="brand-header">
      <h1>{{NEWSLETTER_TITLE}}</h1>
    </div>
    <div class="section">
      {{SECTION_1}}
    </div>
    <hr class="divider">
    <div class="section">
      {{SECTION_2}}
    </div>
    <div class="exclusive">
      {{EXCLUSIVE_SECTION}}
    </div>
    <div class="footer">
      {{FOOTER}}
    </div>
  </div>
</body>
</html>',
'1:1',
''
);

-- 4. Personal
INSERT INTO preset_templates (template_type, name, html_content, aspect_ratio, thumbnail_url) VALUES (
'newsletter',
'Personal',
'<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, ''Segoe UI'', Roboto, ''Helvetica Neue'', Arial, sans-serif;
    background-color: #fdf4ff;
    color: #3b0764;
    line-height: 1.8;
  }
  .container {
    max-width: 580px;
    margin: 0 auto;
    background: #ffffff;
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 4px 20px rgba(147,51,234,0.06);
  }
  .header {
    padding: 40px 36px 28px;
  }
  .header .emoji-wave {
    font-size: 36px;
    display: block;
    margin-bottom: 12px;
  }
  .header h1 {
    margin: 0;
    font-size: 28px;
    font-weight: 700;
    color: #581c87;
    line-height: 1.3;
  }
  .section {
    padding: 20px 36px 28px;
  }
  .section h2 {
    font-size: 20px;
    font-weight: 600;
    color: #7e22ce;
    margin: 0 0 12px 0;
  }
  .section p {
    margin: 0 0 14px 0;
    font-size: 16px;
    color: #4c1d95;
    opacity: 0.85;
  }
  .divider {
    border: none;
    height: 2px;
    background: linear-gradient(90deg, transparent, #e9d5ff, transparent);
    margin: 0 36px;
  }
  .exclusive {
    margin: 16px 24px;
    padding: 24px 28px;
    background: linear-gradient(135deg, #faf5ff, #f3e8ff);
    border-radius: 12px;
    border: 1px solid #e9d5ff;
  }
  .exclusive h2 {
    color: #9333ea;
  }
  .footer {
    padding: 28px 36px;
    text-align: center;
    font-size: 13px;
    color: #a78bfa;
  }
  .footer a { color: #7c3aed; }
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>{{NEWSLETTER_TITLE}}</h1>
    </div>
    <div class="section">
      {{SECTION_1}}
    </div>
    <hr class="divider">
    <div class="section">
      {{SECTION_2}}
    </div>
    <div class="exclusive">
      {{EXCLUSIVE_SECTION}}
    </div>
    <div class="footer">
      {{FOOTER}}
    </div>
  </div>
</body>
</html>',
'1:1',
''
);
