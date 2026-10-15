'use strict'

const fs = require('node:fs')
const path = require('node:path')

// Los tonos son los mismos en todas las fichas del fabricante. Muestreados de
// la paleta impresa en docs/ficha-losetaschile.md el 2026-10-14.
const TONES = Object.freeze(['#d9dadc', '#bfc0c4', '#87888a', '#f3d3a2', '#d3ad6f', '#b7817f'])

// `specs` sale de la ficha del fabricante. Un producto sin ficha no lleva
// specs: se muestra con nombre y precio, y nada inventado.
const BORDE_50 = Object.freeze({ size: '50 × 50 cm', thickness: '3 cm',
  features: ['Antideslizante', 'Atérmico', 'Alta resistencia', 'Interior y exterior'] })
const PASTELON_40 = Object.freeze({ size: '40 × 40 cm', thickness: '2 cm',
  features: ['Alta resistencia', 'Interior y exterior'] })

const CATALOGS = Object.freeze({
  bordes: {
    // `title` es además el pie del documento en WhatsApp y lo que el puente
    // compara para confirmar el envío. Debe coincidir con el que arma el
    // orquestador en reply_to_inbound.
    title: 'Catálogo Bordes de Piscina',
    columns: 2,
    products: [
      { id: 'borde-recto-nariz-50x50', name: 'Borde recto con nariz', specs: BORDE_50,
        images: ['borde-recto-nariz-50x50.jpeg', 'borde-recto-instalado.jpeg'] },
      { id: 'borde-ballena-50x40', name: 'Borde ballena 50 × 40',
        images: ['borde-ballena-50x40.jpeg', 'borde-ballena-instalado.jpeg'] },
      { id: 'esquina-piscina-50x50', name: 'Esquina de piscina', specs: BORDE_50,
        image: 'producto-esquina-piscina-50x50.jpeg' },
      { id: 'extension-borde-piscina-50x50', name: 'Extensión de borde', specs: BORDE_50,
        image: 'producto-extension-borde-piscina-50x50.jpeg' },
    ],
  },
  pastelones: {
    title: 'Catálogo Pastelones',
    columns: 3,
    products: [
      { id: 'laja-espanola-40x40', name: 'Laja española', specs: PASTELON_40,
        image: 'producto-laja-espanola-40x40.jpeg', priceId: 'pastelones-40x40' },
      { id: 'ladrillo-cruzado-40x40', name: 'Ladrillo cruzado', specs: PASTELON_40,
        image: 'producto-ladrillo-cruzado-40x40.jpeg', priceId: 'pastelones-40x40' },
      { id: 'sol-40x40', name: 'Sol', specs: PASTELON_40,
        image: 'producto-sol-40x40.jpeg', priceId: 'pastelones-40x40' },
      { id: 'sol-rustico-40x40', name: 'Sol rústico', specs: PASTELON_40,
        image: 'producto-sol-rustico-40x40.jpeg', priceId: 'pastelones-40x40' },
      { id: 'gregioriano-40x40', name: 'Gregioriano',
        image: 'gregioriano-40x40.jpeg', priceId: 'pastelones-40x40' },
      { id: 'octagonal-piedra-40x40', name: 'Octagonal Piedra',
        image: 'octagonal-piedra-40x40.jpeg', priceId: 'pastelones-40x40' },
    ],
  },
})

const LOGO = 'pooledge-logo.jpeg'

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

function dataUri(imageDir, filename) {
  const type = filename.endsWith('.png') ? 'image/png' : 'image/jpeg'
  return `data:${type};base64,${fs.readFileSync(path.join(imageDir, filename)).toString('base64')}`
}

function renderCatalogHtml(category, prices, imageDir) {
  const catalog = CATALOGS[category]
  if (!catalog || !prices || typeof prices !== 'object' || Array.isArray(prices)) {
    throw new Error('invalid catalog or pricing')
  }
  const cards = catalog.products.map(product => {
    const price = priceLabel(prices[product.priceId || product.id])
    const images = product.images || (product.image ? [product.image] : [])
    const shots = images.length
      ? images.map(filename => `<img src="${dataUri(imageDir, filename)}" alt="${htmlEscape(product.name)}">`).join('')
      : '<div class="no-photo">Fotografía pendiente</div>'
    // Sin ficha del fabricante no se escriben medidas ni atributos.
    const specs = product.specs
      ? `<p class="size">${htmlEscape(product.specs.size)} · ${htmlEscape(product.specs.thickness)} de espesor</p>` +
        `<p class="features">${htmlEscape(product.specs.features.join(' · '))}</p>`
      : ''
    return `<section class="card"><div class="shots${images.length > 1 ? ' pair' : ''}">${shots}</div>` +
      `<div class="details"><h2>${htmlEscape(product.name)}</h2>` +
      `<p class="price">${htmlEscape(price)}</p>${specs}</div></section>`
  }).join('')
  const checked = new Intl.DateTimeFormat('es-CL', {
    timeZone: 'America/Santiago', day: '2-digit', month: '2-digit', year: 'numeric',
  }).format(new Date())
  const swatches = TONES.map(tone =>
    `<span class="tone" style="background:${tone}"></span>`).join('')
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><style>
    @page { size: A4 landscape; margin: 9mm; }
    * { box-sizing: border-box; }
    body { margin: 0; color: #1d2b33; background: #fff;
      font: 13px/1.35 "Helvetica Neue", Arial, sans-serif; }
    header { display: flex; align-items: center; gap: 14px;
      border-bottom: 2px solid #f49c1e; padding-bottom: 8px; margin-bottom: 12px; }
    header img { height: 40px; width: auto; display: block; }
    .heading { flex: 1; }
    h1 { margin: 0; font-size: 21px; letter-spacing: .2px; color: #1d2b33; }
    .asof { color: #7b8a93; font-size: 11px; }
    .grid { display: grid; grid-template-columns: repeat(${catalog.columns}, 1fr); gap: 11px; }
    .card { border: 1px solid #dde5e9; border-radius: 9px; overflow: hidden;
      break-inside: avoid; min-width: 0; background: #fff; }
    /* Todas las fotos quedaron cuadradas tras recortar bandas y extraerlas de
       las fichas, así que el marco cuadrado ya no descarta nada del producto. */
    /* La altura manda: una página A4 apaisada deja ~204px por foto una vez
       descontados cabecera, pie, el texto de cada tarjeta y dos filas. Si se
       dimensiona por ancho, una columna de 500px desborda a dos páginas. */
    .shots { display: flex; gap: 5px; padding: 7px; background: #f3f7f9;
      height: 178px; align-items: center; justify-content: center; }
    .shots img { display: block; height: 100%; width: auto; aspect-ratio: 1 / 1;
      object-fit: cover; border-radius: 5px; }
    .no-photo { color: #7b8a93; font-size: 12px; padding: 40px 0; }
    .details { padding: 8px 11px 11px; }
    h2 { margin: 0; font-size: 14px; font-weight: 700; }
    .price { margin: 3px 0 0; font-size: 15px; font-weight: 700; color: #1593c4; }
    .size { margin: 5px 0 0; font-size: 11.5px; color: #43555f; }
    .features { margin: 2px 0 0; font-size: 10.5px; color: #7b8a93; }
    footer { display: flex; align-items: center; gap: 9px; flex-wrap: wrap;
      border-top: 1px solid #dde5e9; color: #7b8a93;
      margin-top: 12px; padding-top: 7px; font-size: 10.5px; }
    .tone { display: inline-block; width: 17px; height: 11px;
      border: 1px solid #c9d4da; border-radius: 2px; }
    .note { margin-left: auto; }
  </style></head><body>
  <header><img src="${dataUri(imageDir, LOGO)}" alt="PoolEdge">
  <div class="heading"><h1>${htmlEscape(catalog.title)}</h1>
  <span class="asof">Precios consultados el ${htmlEscape(checked)}</span></div></header>
  <main class="grid">${cards}</main>
  <footer><strong>Tonos disponibles:</strong>${swatches}
  <span class="note">Disponibilidad y despacho por confirmar.</span></footer>
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

module.exports = { CATALOGS, TONES, renderCatalogHtml, makeCatalogPdf }
