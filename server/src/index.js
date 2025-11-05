import express from 'express';
import cors from 'cors';
import morgan from 'morgan';
import fetch from 'node-fetch';
import { HttpsProxyAgent } from 'https-proxy-agent';

const TIPPMIX_API_BASE = 'https://api.tippmix.hu';
const PORT = process.env.PORT ? Number(process.env.PORT) : 5000;

const app = express();
app.use(cors());
app.use(morgan('dev'));

const defaultHeaders = {
  'Accept': 'application/json, text/plain, */*',
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
  'Accept-Language': 'hu-HU,hu;q=0.9,en;q=0.8',
  'Origin': 'https://www.tippmix.hu',
  'Referer': 'https://www.tippmix.hu/'
};

const upstreamProxy = process.env.PROXY_URL || process.env.HTTPS_PROXY || process.env.HTTP_PROXY;
const agent = upstreamProxy ? new HttpsProxyAgent(upstreamProxy) : undefined;

async function proxyGet(path, req, res) {
  const url = `${TIPPMIX_API_BASE}${path}`;
  try {
    const response = await fetch(url, { method: 'GET', headers: defaultHeaders, agent });
    const ct = response.headers.get('content-type') || '';
    if (!response.ok) {
      console.error('Tippmix API error', response.status);
      return res.status(response.status).json({ error: `Tippmix API returned ${response.status}` });
    }
    if (ct.includes('text/html')) {
      console.error('Tippmix API returned HTML instead of JSON');
      return res.status(502).json({ error: 'Tippmix API returned HTML instead of JSON' });
    }
    const data = await response.json();
    res.setHeader('Access-Control-Allow-Origin', '*');
    return res.json(data);
  } catch (err) {
    console.error('Proxy error', err);
    return res.status(500).json({ error: 'Proxy failed', message: err?.message || String(err) });
  }
}

app.get('/api/events', (req, res) => proxyGet('/event', req, res));
app.get('/api/search', (req, res) => proxyGet('/tippmix/search', req, res));
app.get('/api/search-filter', (req, res) => proxyGet('/tippmix/search-filter', req, res));

const server = app.listen(PORT, () => {
  console.log(`Proxy listening on http://localhost:${PORT}`);
});
server.on('error', (err) => {
  console.error('Listen error', err);
  const alt = Math.floor(20000 + Math.random() * 20000);
  app.listen(alt, () => {
    console.log(`Proxy listening on fallback port http://localhost:${alt}`);
  });
});
