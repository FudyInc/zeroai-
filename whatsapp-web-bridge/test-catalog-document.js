'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const { CATALOGS, TONES, renderCatalogHtml } = require('./catalog-document')

const imageDir = path.resolve(__dirname, '../frontend/public/catalog/losetaschile')

// Lee el tamaño del encabezado, sin dependencias: el marco SOF de un JPEG o la
// cabecera IHDR de un PNG.
function imageSize(file) {
  const buf = fs.readFileSync(path.join(imageDir, file))
  if (buf.slice(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) {
    return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) }
  }
  let offset = 2
  while (offset < buf.length) {
    if (buf[offset] !== 0xff) { offset += 1; continue }
    const marker = buf[offset + 1]
    if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
      return { height: buf.readUInt16BE(offset + 5), width: buf.readUInt16BE(offset + 7) }
    }
    offset += 2 + buf.readUInt16BE(offset + 2)
  }
  throw new Error(`no se pudo leer el tamaño de ${file}`)
}

function allImages() {
  return Object.values(CATALOGS).flatMap(catalog =>
    catalog.products.flatMap(product => product.images || (product.image ? [product.image] : [])))
}

test('every catalog photo is square, so the frame crops nothing', () => {
  // La regresión: nueve de once eran capturas 591×1280 con bandas negras, y el
  // marco cuadrado descartaba el 54% —incluido el producto. Ya recortadas y
  // extraídas de las fichas, todas quedan cuadradas.
  for (const file of allImages()) {
    const { width, height } = imageSize(file)
    const ratio = width / height
    assert.ok(ratio > 0.9 && ratio < 1.1,
      `${file} mide ${width}×${height} (relación ${ratio.toFixed(2)}); se espera cuadrada`)
  }
})

test('the PoolEdge logo heads both catalogs', () => {
  for (const category of ['bordes', 'pastelones']) {
    const html = renderCatalogHtml(category, { 'pastelones-40x40': 1600 }, imageDir)
    assert.match(html, /<header><img src="data:image\/jpeg;base64,[^"]+" alt="PoolEdge">/)
  }
  // Las fichas del fabricante llevan impreso otro logo; por eso el PDF usa la
  // foto extraída y no la ficha completa.
  assert.ok(allImages().every(file => file !== 'laja-espanola-40x40.jpeg'))
})

test('the caption title is the one the orchestrator announces', () => {
  // index.js manda este texto como pie del documento y lo compara para
  // confirmar el envío; reply_to_inbound anuncia el mismo.
  assert.equal(CATALOGS.bordes.title, 'Catálogo Bordes de Piscina')
  assert.equal(CATALOGS.pastelones.title, 'Catálogo Pastelones')
})

test('border PDF pairs each piece with its installed pool and prices it', () => {
  const html = renderCatalogHtml('bordes', {
    'borde-recto-nariz-50x50': 6000,
    'esquina-piscina-50x50': 3600,
    'borde-ballena-50x40': 5500,
  }, imageDir)
  assert.deepEqual(CATALOGS.bordes.products[0].images,
    ['borde-recto-nariz-50x50.jpeg', 'borde-recto-instalado.jpeg'])
  assert.deepEqual(CATALOGS.bordes.products[1].images,
    ['borde-ballena-50x40.jpeg', 'borde-ballena-instalado.jpeg'])
  assert.equal((html.match(/<section class="card">/g) || []).length, 4)
  // cuatro tarjetas: dos con par de fotos, dos con una, más el logo
  assert.equal((html.match(/<img src="data:image\//g) || []).length, 7)
  assert.match(html, /Borde ballena 50 × 40<\/h2><p class="price">\$5\.500 x unidad/)
  assert.match(html, /Extensión de borde<\/h2><p class="price">Precio por confirmar/)
  assert.doesNotMatch(html, /Fotografía pendiente/)
  assert.doesNotMatch(html, /Flor de lis|Adoquín/)
})

test('specs are shown only for products that have a manufacturer sheet', () => {
  const bordes = renderCatalogHtml('bordes', {}, imageDir)
  assert.equal((bordes.match(/50 × 50 cm · 3 cm de espesor/g) || []).length, 3)
  assert.match(bordes, /Antideslizante · Atérmico · Alta resistencia · Interior y exterior/)
  const pastelones = renderCatalogHtml('pastelones', { 'pastelones-40x40': 1600 }, imageDir)
  assert.equal((pastelones.match(/40 × 40 cm · 2 cm de espesor/g) || []).length, 4)
  // Borde ballena, Gregioriano y Octagonal Piedra no tienen ficha: nada inventado.
  for (const id of ['borde-ballena-50x40', 'gregioriano-40x40', 'octagonal-piedra-40x40']) {
    const product = Object.values(CATALOGS).flatMap(c => c.products).find(p => p.id === id)
    assert.equal(product.specs, undefined, `${id} no debe declarar specs`)
  }
})

test('pastelones PDF contains six photos and the shared active price', () => {
  const html = renderCatalogHtml('pastelones', { 'pastelones-40x40': 1600 }, imageDir)
  assert.equal((html.match(/<section class="card">/g) || []).length, 6)
  assert.equal((html.match(/<img src="data:image\//g) || []).length, 7)   // seis más el logo
  assert.equal((html.match(/\$1\.600 x unidad/g) || []).length, 6)
  assert.doesNotMatch(html, /Flor de lis|Adoquín/)
})

test('the tone palette from the sheets survives in the footer', () => {
  const html = renderCatalogHtml('bordes', {}, imageDir)
  assert.equal(TONES.length, 6)
  for (const tone of TONES) assert.ok(html.includes(`background:${tone}`), `falta el tono ${tone}`)
})
