let records = [];
const msg = (text) => document.querySelector('#msg').textContent = text;
const send = (tabId, message) => new Promise(resolve => chrome.scripting?.executeScript ? chrome.scripting.executeScript({target:{tabId}, func:() => window.__publicReelCollector?.()}).then(r => resolve(r?.[0]?.result || [])) : resolve([]));
const getSource = (url) => {
  const u = new URL(url); const parts = u.pathname.split('/').filter(Boolean);
  if (parts[0] === 'explore' && parts[1] === 'tags') return {kind:'hashtag', query:decodeURIComponent(parts[2] || '')};
  if (parts[0] === 'explore' && (parts[1] === 'search' || parts[1] === 'searches')) return {kind:'keyword', query:decodeURIComponent(parts.slice(2).join(' ') || '')};
  return {kind:'account', query:decodeURIComponent(parts[0] || '')};
};

document.querySelector('#collect').onclick = async () => {
  const [tab] = await chrome.tabs.query({active:true,currentWindow:true});
  if (!tab?.url?.includes('instagram.com')) return msg('Open Instagram first.');
  try {
    const collected = await send(tab.id);
    const source = getSource(tab.url);
    const sourceKind = source.kind;
    const sourceQuery = source.query;
    const merged = new Map(records.map(r => [r.reel_url, r]));
    for (const r of collected) merged.set(r.reel_url, {...r, source_kind: sourceKind, source_query: sourceQuery});
    const counts = new Map();
    records = [...merged.values()].filter(r => {
      const key = `${r.source_kind || 'manual'}:${r.source_query || ''}`;
      const count = counts.get(key) || 0;
      if (count >= 500) return false;
      counts.set(key, count + 1);
      return true;
    });
    await chrome.storage.local.set({records});
    document.querySelector('#download').disabled = !records.length;
    const sourceCount = records.filter(r => r.source_kind === sourceKind && r.source_query === sourceQuery).length;
    msg(`Collected ${collected.length} visible reels.\nUnique records for ${sourceKind}:${sourceQuery}: ${sourceCount}/500.`);
  } catch (e) { msg(`Could not collect: ${e.message}`); }
};

async function collectFromTab(tab) {
  const collected = await send(tab.id);
  const source = getSource(tab.url);
  const sourceKind = source.kind;
  const sourceQuery = source.query;
  const merged = new Map(records.map(r => [r.reel_url, r]));
  for (const r of collected) merged.set(r.reel_url, {...r, source_kind: sourceKind, source_query: sourceQuery});
  const counts = new Map();
  records = [...merged.values()].filter(r => {
    const key = `${r.source_kind || 'manual'}:${r.source_query || ''}`;
    const count = counts.get(key) || 0;
    if (count >= 500) return false;
    counts.set(key, count + 1); return true;
  });
  await chrome.storage.local.set({records});
  document.querySelector('#download').disabled = !records.length;
  return {collected: collected.length, sourceKind, sourceQuery, sourceCount: records.filter(r => r.source_kind === sourceKind && r.source_query === sourceQuery).length};
}

document.querySelector('#auto').onclick = async () => {
  const [tab] = await chrome.tabs.query({active:true,currentWindow:true});
  if (!tab?.url?.includes('instagram.com')) return msg('Open Instagram first.');
  document.querySelector('#auto').disabled = true;
  try {
    let totalVisible = 0, lastHeight = 0, unchanged = 0;
    for (let page = 0; page < 120; page++) {
      const result = await collectFromTab(tab); totalVisible += result.collected;
      msg(`Scanning ${result.sourceKind}:${result.sourceQuery}…\n${result.sourceCount}/500 unique records collected.`);
      const scrollResult = await chrome.scripting.executeScript({target:{tabId:tab.id}, func:() => { const before = document.documentElement.scrollHeight; window.scrollBy(0, Math.max(500, Math.floor(window.innerHeight * 0.8))); return {before, after: document.documentElement.scrollHeight}; }});
      const height = scrollResult?.[0]?.result?.after || 0;
      unchanged = height === lastHeight ? unchanged + 1 : 0; lastHeight = height;
      await new Promise(resolve => setTimeout(resolve, 1200));
      if (unchanged >= 4 || records.filter(r => r.source_kind === result.sourceKind && r.source_query === result.sourceQuery).length >= 500) break;
    }
    const finalSource = getSource(tab.url);
    const finalCount = records.filter(r => r.source_kind === finalSource.kind && r.source_query === finalSource.query).length;
    msg(`Automatic scan complete.\nVisible candidates seen: ${totalVisible}.\nRecords retained for this source: ${finalCount}/500.`);
  } catch (e) { msg(`Automatic scan stopped: ${e.message}`); }
  finally { document.querySelector('#auto').disabled = false; }
};

document.querySelector('#download').onclick = async () => {
  const blob = new Blob([JSON.stringify({records}, null, 2)], {type:'application/json'});
  const url = URL.createObjectURL(blob);
  await chrome.downloads.download({url, filename:'instagram_reels_collection.json', saveAs:true});
  msg('JSON downloaded. Import it in the local dashboard.');
};
chrome.storage.local.get('records', r => { records = r.records || []; document.querySelector('#download').disabled = !records.length; });
