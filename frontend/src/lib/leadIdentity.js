const text = (value) => typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : ''
const named = (value) => /\p{L}/u.test(value) ? value : ''

export function leadIdentity(lead = {}) {
  const name = named(text(lead.name))
  const company = named(text(lead.company))
  return {
    title: name || company || 'Sin nombre registrado',
    company: name && company && name.toLocaleLowerCase() !== company.toLocaleLowerCase() ? company : '',
    phone: text(lead.phone),
    email: text(lead.email),
  }
}
