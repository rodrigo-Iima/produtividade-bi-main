#!/usr/bin/env bash

# Atualiza a origem IPv4 da regra de administração da EC2 sem abrir uma nova
# regra a cada troca de rede. A execução é somente leitura por padrão; use
# --apply para modificar o Security Group.

set -Eeuo pipefail

AWS_REGION="${AWS_REGION:-sa-east-1}"
INSTANCE_ID="${EC2_INSTANCE_ID:-}"
SECURITY_GROUP_ID="${SECURITY_GROUP_ID:-}"
SSH_PORT="${SSH_PORT:-32}"
RULE_DESCRIPTION="${EC2_IP_RULE_DESCRIPTION:-produtividade-bi-admin-ip}"
APPLY=false

usage() {
    cat <<'EOF'
Uso:
  scripts/update_ec2_ip.sh --security-group-id sg-xxxxxxxx [--port 32] [--apply]
  scripts/update_ec2_ip.sh --instance-id i-xxxxxxxx [--port 32] [--apply]

Variáveis opcionais:
  AWS_REGION                 Região AWS (padrão: sa-east-1)
  EC2_INSTANCE_ID            ID da instância, se não for passado por argumento
  SECURITY_GROUP_ID          ID do Security Group, se não for passado por argumento
  SSH_PORT                   Porta TCP de administração (padrão: 32)
  EC2_IP_RULE_DESCRIPTION    Descrição usada na regra gerenciada pelo script

Sem --apply, o script apenas mostra o que seria alterado.
EOF
}

fail() {
    printf 'Erro: %s\n' "$*" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)
            [[ $# -ge 2 ]] || fail "--region exige um valor"
            AWS_REGION="$2"
            shift 2
            ;;
        --instance-id)
            [[ $# -ge 2 ]] || fail "--instance-id exige um valor"
            INSTANCE_ID="$2"
            shift 2
            ;;
        --security-group-id)
            [[ $# -ge 2 ]] || fail "--security-group-id exige um valor"
            SECURITY_GROUP_ID="$2"
            shift 2
            ;;
        --port)
            [[ $# -ge 2 ]] || fail "--port exige um valor"
            SSH_PORT="$2"
            shift 2
            ;;
        --apply)
            APPLY=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            fail "opção desconhecida: $1"
            ;;
    esac
done

command -v aws >/dev/null 2>&1 || fail "AWS CLI não encontrada"
command -v curl >/dev/null 2>&1 || fail "curl não encontrado"
[[ "$SSH_PORT" =~ ^[0-9]+$ ]] || fail "a porta deve ser numérica"
(( SSH_PORT >= 1 && SSH_PORT <= 65535 )) || fail "a porta deve estar entre 1 e 65535"

aws_ec2() {
    aws --region "$AWS_REGION" ec2 "$@"
}

if [[ -z "$SECURITY_GROUP_ID" ]]; then
    [[ -n "$INSTANCE_ID" ]] || fail "informe --security-group-id ou --instance-id"

    security_groups="$(aws_ec2 describe-instances \
        --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].SecurityGroups[].GroupId' \
        --output text)" || fail "não foi possível consultar a instância $INSTANCE_ID"

    read -r -a security_group_array <<< "$security_groups"
    [[ ${#security_group_array[@]} -eq 1 ]] || fail \
        "a instância possui ${#security_group_array[@]} Security Groups; informe --security-group-id explicitamente"
    SECURITY_GROUP_ID="${security_group_array[0]}"
fi

[[ "$SECURITY_GROUP_ID" =~ ^sg-[a-zA-Z0-9]+$ ]] || \
    fail "Security Group inválido: $SECURITY_GROUP_ID"

current_ip="$(curl -4fsS --max-time 10 https://checkip.amazonaws.com | tr -d '[:space:]')" \
    || fail "não foi possível descobrir o IPv4 público atual"

[[ "$current_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || \
    fail "o serviço de IP retornou um valor inválido: $current_ip"

IFS=. read -r octet1 octet2 octet3 octet4 <<< "$current_ip"
for octet in "$octet1" "$octet2" "$octet3" "$octet4"; do
    (( 10#$octet <= 255 )) || fail "IPv4 inválido: $current_ip"
done

rules_text="$(aws_ec2 describe-security-group-rules \
    --filters "Name=group-id,Values=$SECURITY_GROUP_ID" "Name=is-egress,Values=false" \
    --query "SecurityGroupRules[?IpProtocol=='tcp' && FromPort==\`$SSH_PORT\` && ToPort==\`$SSH_PORT\`].[SecurityGroupRuleId,CidrIpv4,Description]" \
    --output text)" || fail "não foi possível consultar as regras do Security Group"

rule_ids=()
rule_cidrs=()
rule_descriptions=()
while IFS=$'\t' read -r rule_id cidr description; do
    [[ -n "${rule_id:-}" && "$rule_id" != "None" ]] || continue
    [[ -n "${cidr:-}" && "$cidr" != "None" ]] || continue
    rule_ids+=("$rule_id")
    rule_cidrs+=("$cidr")
    rule_descriptions+=("${description:-}")
done <<< "$rules_text"

selected_index=-1
marked_count=0
for index in "${!rule_ids[@]}"; do
    if [[ "${rule_descriptions[$index]}" == "$RULE_DESCRIPTION" ]]; then
        selected_index="$index"
        ((marked_count += 1))
    fi
done

if (( marked_count > 1 )); then
    fail "há mais de uma regra marcada como '$RULE_DESCRIPTION'; revisão manual necessária"
fi

if (( marked_count == 0 )); then
    if (( ${#rule_ids[@]} != 1 )); then
        fail "não foi encontrada uma única regra TCP/$SSH_PORT IPv4 para atualizar; informe a regra por descrição ou remova a ambiguidade manualmente"
    fi
    selected_index=0
    [[ "${rule_cidrs[0]}" == */32 ]] || fail \
        "a única regra TCP/$SSH_PORT não é restrita a um /32 (${rule_cidrs[0]}); alteração abortada por segurança"
fi

rule_id="${rule_ids[$selected_index]}"
old_cidr="${rule_cidrs[$selected_index]}"
[[ "$old_cidr" == */32 ]] || fail \
    "a regra selecionada não é restrita a um /32 ($old_cidr); alteração abortada por segurança"
new_cidr="$current_ip/32"

printf 'Região:              %s\n' "$AWS_REGION"
printf 'Security Group:      %s\n' "$SECURITY_GROUP_ID"
printf 'Regra:               %s\n' "$rule_id"
printf 'Porta:               %s/tcp\n' "$SSH_PORT"
printf 'Origem atual:        %s\n' "$old_cidr"
printf 'Novo IPv4:           %s\n' "$new_cidr"

if [[ "$old_cidr" == "$new_cidr" ]]; then
    printf 'Nenhuma alteração necessária; o IP já está atualizado.\n'
    exit 0
fi

if [[ "$APPLY" != true ]]; then
    printf '\nSimulação. Para aplicar, repita o comando acrescentando --apply.\n'
    exit 0
fi

rule_payload="$(printf '[{"SecurityGroupRuleId":"%s","SecurityGroupRule":{"IpProtocol":"tcp","FromPort":%s,"ToPort":%s,"CidrIpv4":"%s","Description":"%s"}}]' \
    "$rule_id" "$SSH_PORT" "$SSH_PORT" "$new_cidr" "$RULE_DESCRIPTION")"

aws_ec2 modify-security-group-rules \
    --group-id "$SECURITY_GROUP_ID" \
    --security-group-rules "$rule_payload" >/dev/null

printf 'Regra atualizada com sucesso: %s -> %s\n' "$old_cidr" "$new_cidr"
