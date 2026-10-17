/* Brand assets stay local; changing an icon does not imply a provider connection. */
export default function ChannelIcon({ channel }) {
  if (channel === 'email') return <img src="/technology/gmail.png" alt="Gmail" width="32" height="32" className="object-contain" />
  if (channel === 'call') return <img src="/technology/phone-ios.svg" alt="Teléfono de iPhone" width="50" height="50" className="max-w-none object-contain" />
  if (channel === 'ig') return <span role="img" aria-label="Instagram" style={{ display: 'block', width: 30, height: 30, background: 'radial-gradient(circle at 30% 107%, #fdf497 0%, #fdf497 5%, #fd5949 45%, #d6249f 60%, #285aeb 90%)', mask: 'url(/technology/instagram.svg) center / contain no-repeat' }} />
  return <span role="img" aria-label="WhatsApp" style={{ display: 'block', width: 32, height: 32, backgroundColor: '#25D366', mask: 'url(/technology/whatsapp.svg) center / contain no-repeat' }} />
}
