'use strict'

const assert = require('node:assert/strict')
const path = require('node:path')
const test = require('node:test')
const { CATALOGS, renderCatalogHtml } = require('./catalog-document')

const imageDir = path.resolve(__dirname, '../frontend/public/catalog/losetaschile')

test('border PDF source includes supplied ballena photos and its active price', () => {
  const html = renderCatalogHtml('bordes', {
    'borde-recto-nariz-50x50': 6000,
    'esquina-piscina-50x50': 3600,
    'borde-ballena-50x40': 5500,
  }, imageDir)
  assert.equal(CATALOGS.bordes.products.filter(product => product.image).length, 3)
  assert.deepEqual(CATALOGS.bordes.products[3].images,
    ['borde-ballena-50x40.jpeg', 'borde-ballena-instalado.jpeg'])
  assert.equal((html.match(/<section class="card">/g) || []).length, 4)
  assert.equal((html.match(/<img src="data:image\//g) || []).length, 5)
  assert.match(html, /Borde ballena 50 × 40<\/strong><strong class="price">\$5\.500 x unidad/)
  assert.match(html, /Extensión de borde<\/strong><strong class="price">Precio por confirmar/)
  assert.doesNotMatch(html, /Fotografía pendiente/)
  assert.doesNotMatch(html, /Flor de lis|Adoquín|50 × 50|40 × 40/)
})

test('pastelones PDF source contains six photos and the shared active price', () => {
  const html = renderCatalogHtml('pastelones', { 'pastelones-40x40': 1600 }, imageDir)
  assert.equal((html.match(/<section class="card">/g) || []).length, 6)
  assert.equal((html.match(/<img src="data:image\//g) || []).length, 6)
  assert.equal((html.match(/\$1\.600 x unidad/g) || []).length, 6)
  assert.doesNotMatch(html, /Flor de lis|Adoquín/)
})
