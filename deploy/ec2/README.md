# Deployment EC2

O PostgreSQL deste deployment exige TLS e autenticação SCRAM em toda conexão
TCP. O acesso administrativo pelo socket Unix dentro do contêiner permanece
disponível para recuperação.

## Arquivos TLS

Antes de iniciar o Compose, disponibilize em `postgres/tls/`:

- `ca.crt`: certificado público da autoridade que assinou o servidor;
- `server.crt`: certificado do PostgreSQL;
- `server.key`: chave privada do servidor, com permissão `0600` e pertencente
  ao UID do PostgreSQL no contêiner.

O certificado do servidor deve ter SAN para todos os nomes usados pelos
clientes. Para este Compose, inclua pelo menos `DNS:postgres`. Para acesso
externo com `verify-full`, inclua também o DNS ou IP público utilizado.

Certificados, chaves e arquivos auxiliares desse diretório são ignorados pelo
Git.

## Bind e firewall

O valor seguro padrão é:

```dotenv
POSTGRES_BIND_ADDRESS=127.0.0.1
```

Para acesso direto externo, use `0.0.0.0` somente depois de restringir a porta
TCP `5432` no Security Group ou firewall do provedor aos endereços aprovados,
preferencialmente regras individuais `/32`.

Se uma integração exigir `0.0.0.0/0`, mantenha a política versionada de
`postgres/config/pg_hba.conf`. Ela aceita externamente somente
`produtividade_reader` e rejeita os usuários operacionais fora da rede Docker.

## Usuário externo

O usuário externo deve ser separado dos usuários do ETL e do Metabase:

- role: `produtividade_reader`;
- sem privilégios de superusuário, criação, replicação ou escrita;
- até 10 conexões simultâneas;
- transações read-only por padrão;
- `SELECT` somente nas views do schema `public`;
- timeout de 120 segundos por comando.

A senha não deve ser versionada. Depois de criar novas views, reaplique:

```bash
docker exec -i ec2-postgres-1 \
  psql -U produtividade -d produtividade \
  < postgres/security/grant_dashboard_views.sql
```

## Clientes

O ETL deve verificar a CA:

```dotenv
POSTGRES_SSLMODE=verify-full
PGSSLROOTCERT=/caminho/para/ca.crt
```

Exemplo de acesso com `psql`:

```bash
psql \
  "host=<host-publico> port=5432 dbname=produtividade \
  user=produtividade_reader sslmode=verify-full \
  sslrootcert=/caminho/para/ca.crt"
```

Faça um backup lógico e valide sua leitura antes de recriar PostgreSQL e
Metabase após alterações de TLS.
