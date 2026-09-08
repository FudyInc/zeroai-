/* Brand assets stay local; changing an icon does not imply a provider connection. */
export default function ChannelIcon({ channel }) {
  if (channel === 'email') return <img src="/technology/gmail.png" alt="Gmail" width="32" height="32" className="object-contain" />
  if (channel === 'call') return <img src="/technology/phone-ios.svg" alt="Teléfono de iPhone" width="50" height="50" className="max-w-none object-contain" />
  return <span role="img" aria-label="WhatsApp" style={{ display: 'block', width: 32, height: 32, backgroundColor: '#25D366', mask: 'url(/technology/whatsapp.svg) center / contain no-repeat' }} />
}
