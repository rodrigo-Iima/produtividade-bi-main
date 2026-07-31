# Certificados PostgreSQL

Este diretório recebe os arquivos gerados diretamente no servidor:

- `ca.crt`: certificado público da autoridade local;
- `server.crt`: certificado do PostgreSQL assinado pela autoridade;
- `server.key`: chave privada do PostgreSQL.

Os certificados e as chaves são ignorados pelo Git. O `server.key` deve
pertencer ao usuário do PostgreSQL no contêiner e ter permissão `0600`.
