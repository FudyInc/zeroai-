'use strict'

const fs = require('node:fs')
const path = require('node:path')

const CATALOGS = Object.freeze({
  bordes: {
    title: 'Catálogo Bordes de Piscina',
    columns: 2,
    products: [
      { id: 'borde-recto-nariz-50x50', name: 'Borde recto con nariz', image: 'borde-recto-nariz-50x50.png' },
      { id: 'esquina-piscina-50x50', name: 'Esquina de piscina', image: 'esquina-piscina-50x50.jpeg' },
      { id: 'extension-borde-piscina-50x50', name: 'Extensión de borde', image: 'extension-borde-piscina-50x50.jpeg' },
      { id: 'borde-ballena-50x40', name: 'Borde ballena 50 × 40',
        images: ['borde-ballena-50x40.jpeg', 'borde-ballena-instalado.jpeg'] },
    ],
  },
  pastelones: {
    title: 'Catálogo Pastelones',
    columns: 3,
    products: [
      { id: 'laja-espanola-40x40', name: 'Laja española', image: 'laja-espanola-40x40.jpeg', priceId: 'pastelones-40x40' },
      { id: 'ladrillo-cruzado-40x40', name: 'Ladrillo cruzado', image: 'ladrillo-cruzado-40x40.jpeg', priceId: 'pastelones-40x40' },
      { id: 'sol-40x40', name: 'Sol', image: 'sol-40x40.jpeg', priceId: 'pastelones-40x40' },
      { id: 'sol-rustico-40x40', name: 'Sol rústico', image: 'sol-rustico-40x40.jpeg', priceId: 'pastelones-40x40' },
      { id: 'gregioriano-40x40', name: 'Gregioriano', image: 'gregioriano-40x40.jpeg', priceId: 'pastelones-40x40' },
      { id: 'octagonal-piedra-40x40', name: 'Octagonal Piedra', image: 'octagonal-piedra-40x40.jpeg', priceId: 'pastelones-40x40' },
    ],
  },
})

function htmlEscape(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char])
}

function priceLabel(value) {
  const amount = Number(value)
  return Number.isFinite(amount) && amount > 0 && amount <= 100000000
    ? `$${new Intl.NumberFormat('es-CL', { maximumFractionDigits: 0 }).format(amount)} x unidad`
    : 'Precio por confirmar'
}

function renderCatalogHtml(category, prices, imageDir) {
  const catalog = CATALOGS[category]
  if (!catalog || !prices || typeof prices !== 'object' || Array.isArray(prices)) {
    throw new Error('invalid catalog or pricing')
  }
  const cards = catalog.products.map(product => {
    const price = priceLabel(prices[product.priceId || product.id])
    const images = product.images || (product.image ? [product.image] : [])
    const illustration = images.length
      ? images.map(filename => `<img src="data:${filename.endsWith('.png') ? 'image/png' : 'image/jpeg'};base64,${
        fs.readFileSync(path.join(imageDir, filename)).toString('base64')}" alt="${htmlEscape(product.name)}">`).join('')
      : '<div class="no-photo">Fotografía pendiente</div>'
    return `<section class="card"><div class="photo${images.length > 1 ? ' pair' : ''}">${illustration}</div>` +
      `<div class="details"><strong>${htmlEscape(product.name)}</strong><strong class="price">${htmlEscape(price)}</strong></div></section>`
  }).join('')
  const checked = new Intl.DateTimeFormat('es-CL', {
    timeZone: 'America/Santiago', day: '2-digit', month: '2-digit', year: 'numeric',
  }).format(new Date())
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><style>
    @page { size: A4 landscape; margin: 10mm; }
    * { box-sizing: border-box; }
    body { margin: 0; color: #23302a; font: 14px Arial, sans-serif; }
    header { display: flex; justify-content: space-between; align-items: baseline;
      border-bottom: 2px solid #315c45; padding-bottom: 7px; margin-bottom: 12px; }
    h1 { margin: 0; font-size: 24px; }
    small { color: #657168; }
    .grid { display: grid; grid-template-columns: repeat(${catalog.columns}, 1fr);
      gap: 10px; }
    .card { border: 1px solid #d5dfd6; border-radius: 8px; overflow: hidden;
      break-inside: avoid; min-width: 0; }
    .photo { height: 210px; display: flex; gap: 6px;
      align-items: center; justify-content: center; background: #f4f6f2; }
    img { display: block; width: 200px; height: 200px; object-fit: cover; }
    .pair img { max-width: 48%; }
    .no-photo { color: #657168; font-size: 13px; }
    .details { display: flex; flex-direction: column; gap: 4px;
      align-items: flex-start; padding: 8px 10px; }
    .details strong { font-size: 13px; }
    .details .price { font-size: 15px; font-weight: 700; color: #315c45; }
    footer { border-top: 1px solid #d5dfd6; color: #657168; margin-top: 12px;
      padding-top: 7px; font-size: 11px; }
  </style></head><body><header><h1>${htmlEscape(catalog.title)}</h1>
  <small>Precios consultados el ${htmlEscape(checked)}</small></header>
  <main class="grid">${cards}</main><footer>Disponibilidad y despacho por confirmar.</footer>
  </body></html>`
}

async function makeCatalogPdf(browser, category, prices, imageDir) {
  const html = renderCatalogHtml(category, prices, imageDir)
  const page = await browser.newPage()
  try {
    await page.setContent(html, { waitUntil: 'load' })
    return Buffer.from(await page.pdf({ format: 'A4', landscape: true,
      printBackground: true, preferCSSPageSize: true }))
  } finally {
    await page.close()
  }
}

module.exports = { CATALOGS, renderCatalogHtml, makeCatalogPdf }
