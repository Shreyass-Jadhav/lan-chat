# Generates a self-signed cert.pem/key.pem (valid for localhost, 127.0.0.1 and your LAN IP).
# Run once: python make_cert.py  -> restart the server to enable HTTPS/WSS.
import datetime, ipaddress
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from config import BASE_DIR, get_lan_ip

ip = get_lan_ip()
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "LAN Chat")])
san = x509.SubjectAlternativeName([
    x509.DNSName("localhost"),
    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    x509.IPAddress(ipaddress.ip_address(ip)),
])
now = datetime.datetime.now(datetime.timezone.utc)
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(san, critical=False).sign(key, hashes.SHA256()))
(BASE_DIR / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
(BASE_DIR / "key.pem").write_bytes(key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
print(f"Created cert.pem / key.pem for {ip}. Restart the server to enable HTTPS.")
