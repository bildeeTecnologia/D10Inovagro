AREAS = {
    "pessoas": {
        "title": "Pessoas",
        "description": "Organize a entrada de pessoas e mantenha os vínculos com as empresas e unidades.",
        "guidance": "Para uma nova contratação, comece pela pré-admissão. Para carregar vários cadastros, use a carga cadastral.",
        "capability": "admissions",
        "prefixes": ("/admissoes/", "/importacao/cadastro/"),
        "tools": [
            {
                "title": "Pré-admissões", "route": "admission_list", "capability": "admissions",
                "description": "Convide o candidato, confira suas respostas e converta a aprovação em colaborador e vínculo.",
                "example": "Uma pessoa vai começar na próxima semana: envie o formulário e confira os dados antes de criar o vínculo.",
                "button": "Gerenciar pré-admissões",
            },
            {
                "title": "Carga cadastral", "route": "roster_import", "capability": "admissions",
                "description": "Importe unidades, colaboradores e vínculos por planilha, com prévia antes da confirmação.",
                "example": "Você recebeu uma lista de colaboradores de uma unidade: baixe o modelo, preencha e revise a prévia.",
                "button": "Importar cadastros",
            },
        ],
    },
    "operacao": {
        "title": "Operação",
        "description": "Registre o que acontece no campo e acompanhe as solicitações do dia a dia.",
        "guidance": "Use o app para registrar ocorrências, a lista e o calendário para acompanhar, e a comunicação para esclarecer pendências.",
        "capability": "office",
        "prefixes": ("/campo/", "/lancamentos/", "/calendario/", "/comunicacao/"),
        "tools": [
            {
                "title": "App do líder", "route": "field_app", "capability": "field",
                "description": "Registre ocorrências em poucos passos e acompanhe a fila de sincronização.",
                "example": "Houve dispensa por chuva: selecione o colaborador, informe a data e descreva o motivo.",
                "button": "Abrir app do líder",
            },
            {
                "title": "Lançamentos", "route": "event_list", "capability": "field",
                "description": "Consulte os eventos registrados e acompanhe sua situação.",
                "example": "Confira se a ocorrência enviada ontem já aparece na lista antes de lançar novamente.",
                "button": "Consultar lançamentos",
            },
            {
                "title": "Calendário", "route": "event_calendar", "capability": "field",
                "description": "Veja os registros organizados por dia para entender a sequência de acontecimentos.",
                "example": "Revise as ocorrências de uma semana antes de conversar com o líder da unidade.",
                "button": "Ver calendário",
            },
            {
                "title": "Comunicação", "route": "communications", "capability": "field",
                "description": "Troque mensagens e acompanhe solicitações com responsável, prazo e situação.",
                "example": "Uma informação ficou incompleta: abra uma pendência para o responsável esclarecer.",
                "button": "Acompanhar comunicação",
            },
        ],
    },
    "fechamento": {
        "title": "Fechamento",
        "description": "Prepare as regras, confira os resultados e conclua o ciclo com rastreabilidade.",
        "guidance": "Comece verificando as pendências. Confira eventos e valores antes de aprovar pagamentos e encerrar a competência.",
        "capability": "office",
        "prefixes": ("/regras/", "/conferencia/", "/fechamento/", "/pagamentos/", "/saude/", "/importacao/", "/calculo/"),
        "tools": [
            {
                "title": "Saúde da operação", "route": "health_dashboard", "capability": "office",
                "description": "Identifique inconsistências e pendências que precisam de atenção antes do fechamento.",
                "example": "Antes de encerrar o mês, veja se existem vínculos inválidos ou eventos pendentes.",
                "button": "Verificar pendências",
            },
            {
                "title": "Regras e rubricas", "route": "rule_list", "capability": "rules",
                "description": "Consulte e configure as regras autorizadas e as rubricas usadas na conferência.",
                "example": "Uma verba fixa foi autorizada: cadastre a regra e os vínculos antes de gerar os valores.",
                "button": "Gerenciar regras",
            },
            {
                "title": "Conferência", "route": "conference", "capability": "review",
                "description": "Revise eventos, valores e memórias de cálculo antes de aprovar ou rejeitar.",
                "example": "Confira o motivo e o valor de um adicional antes de aprovar o evento.",
                "button": "Conferir eventos e valores",
            },
            {
                "title": "Importar folha", "route": "import_workbook", "capability": "admissions",
                "description": "Analise a prévia de uma folha XLSX ou PDF sem alterar pagamentos automaticamente.",
                "example": "A contabilidade enviou a folha: importe o arquivo e revise os totais e as diferenças.",
                "button": "Analisar arquivo da folha",
            },
            {
                "title": "Pagamentos", "route": "payment_cycles", "capability": "office",
                "description": "Consulte os ciclos mensal e do dia 10 e acompanhe os valores e aprovações.",
                "example": "Revise os lançamentos do ciclo do dia 10 antes de solicitar a aprovação.",
                "button": "Consultar ciclos de pagamento",
            },
            {
                "title": "Encerrar competência", "route": "closing", "capability": "office",
                "description": "Verifique os requisitos e finalize a competência após a conferência e as aprovações.",
                "example": "Todos os eventos foram tratados e os ciclos aprovados: confira os bloqueios antes de encerrar.",
                "button": "Abrir fechamento do mês",
            },
        ],
    },
}


def area_for_path(path):
    for slug, area in AREAS.items():
        if path.startswith(area["prefixes"]):
            return {"slug": slug, "title": area["title"]}
    return None


def available_tools(area, access):
    return [tool for tool in area["tools"] if access[tool["capability"]]]
