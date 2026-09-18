# Scoped Memory

[中文](README.md) · **Português** · [English](README.en.md)

Quando um projeto é interrompido, o problema raramente é esquecer uma frase da conversa. O que faz falta é lembrar por que uma decisão foi tomada, quais caminhos já foram tentados e de onde o trabalho deve continuar.

Scoped Memory é uma ferramenta local de memória de engenharia para Codex e DeepSeek Harness. Ela separa informações duráveis por pessoa, projeto e tarefa em andamento e usa scripts determinísticos para converter o código em fatos estruturados e compactos. Outra conversa ou agente pode consumir decisões e relações do projeto diretamente, sem reler todo o histórico nem transformar primeiro o código em texto narrativo.

## O que vale a pena guardar

- Preferências duradouras de trabalho, como estilo de código e formato de entrega.
- Decisões de arquitetura, limites e fatos verificados que pertencem a um projeto específico.
- O ponto em que uma tarefa parou, o que ainda falta e quais tentativas já deram errado.

Senhas, chaves, dados pessoais, conversas completas e grandes saídas de comandos não devem ser guardados. A memória serve para retomar o trabalho, não para criar uma segunda cópia do histórico de conversas.

## Projetos permanecem separados

Cada projeto recebe uma identidade própria. Por padrão, a memória de um projeto não aparece em outro. O compartilhamento só acontece quando a pessoa informa claramente de qual projeto deseja herdar conteúdo.

Worktrees do mesmo repositório Git compartilham a mesma identidade, portanto é possível alternar entre elas sem perder o contexto. Uma cópia comum ou um novo clone não herda essa identidade automaticamente. Isso evita misturar projetos que apenas se parecem.

## Onde os dados ficam

Tudo permanece no computador por padrão. Não é necessário contratar um serviço na nuvem nem fornecer uma chave adicional. Os registros são mantidos em SQLite e acompanhados por um arquivo JSONL que pode ser conferido e transportado.

Uma lembrança antiga nunca é alterada em silêncio. Uma correção cria um novo registro e aponta para aquele que substituiu. Esquecer um assunto também cria uma marca no histórico. Assim, é possível entender o que aconteceu e verificar se o registro continua íntegro.

## Como funciona no Codex

Ao iniciar ou retomar uma tarefa, e também depois da compactação de contexto, o plugin recupera uma pequena seleção da memória relevante para o projeto atual. Existe um limite claro de tamanho; o histórico inteiro não volta para a conversa.

Também é possível usar a linha de comando ou as ferramentas MCP para registrar decisões, criar um ponto de continuação, consultar lembranças ou esquecer um assunto. As operações de leitura não alteram dados, e as operações de escrita têm permissões explícitas.

## Camada de engenharia EIR/1

`memory_ingest_project` examina o projeto sem chamar um modelo e produz `EIR/1`: impressões digitais dos arquivos, linguagens, símbolos, relações de importação, papel dos testes, dependências dos manifestos e estado do Git. O índice não guarda o conteúdo do código e ignora arquivos de ambiente, possíveis segredos, binários e arquivos grandes demais.

`memory_engineering_context` devolve um pequeno pacote JSON selecionado por consulta e orçamento de tokens. O modelo consome símbolos e relações diretamente; a conversão para linguagem natural fica reservada ao resultado final destinado às pessoas.

```bash
scripts/scoped-memory --home /tmp/scoped-memory-demo ingest .
scripts/scoped-memory --home /tmp/scoped-memory-demo engineering-context . --query memory --token-budget 1200
```

## DeepSeek Harness

O DeepSeek Harness aceita servidores MCP locais por stdio, portanto pode usar o mesmo serviço diretamente:

Primeiro instale o serviço de linha de comando em um ambiente isolado: `pipx install git+https://github.com/lixuanfan567-png/scoped-memory.git`.

```yaml
- insert:
    - id: mcp-scoped-memory
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: scoped_memory
        transport: stdio
        command: scoped-memory-mcp
        cwd: !!js process.cwd()
        env:
          SCOPED_MEMORY_HOME: /caminho/absoluto/para/scoped-memory-data
```

O Harness recebe `mcp__scoped_memory__memory_ingest_project`, `mcp__scoped_memory__memory_engineering_context` e as ferramentas de memória existentes. Codex e DeepSeek Harness podem compartilhar o mesmo armazenamento local sem perder o isolamento entre projetos.

## Desenvolvimento local

É necessário Python 3.10 ou mais recente. Para executar os testes:

```bash
python3 -m unittest discover -s tests -v
```

Para gerar o pacote:

```bash
python3 -m pip wheel . --no-deps
```

Para inicializar um projeto de teste e consultar o estado:

```bash
scripts/scoped-memory --home /tmp/scoped-memory-demo init .
scripts/scoped-memory --home /tmp/scoped-memory-demo status .
```

Os testes cobrem isolamento entre projetos e tarefas, herança explícita, worktrees, clones independentes, gravações simultâneas, correções, esquecimento, orçamento de texto em chinês, extração EIR, exclusão de arquivos sensíveis, inicialização do Codex, chamadas MCP e recuperação do registro de auditoria.

## Situação atual

Este ainda é um projeto em fase inicial. O armazenamento, as regras de isolamento, a inicialização no Codex e as chamadas MCP já foram verificados por testes automáticos e por uma execução real, mas a interface ainda pode mudar antes de uma versão estável.

Veja [CONTRIBUTING.md](CONTRIBUTING.md) para contribuir e [SECURITY.md](SECURITY.md) para conhecer os limites de segurança e a forma de relatar problemas.

Licença MIT. Consulte [LICENSE](LICENSE).
