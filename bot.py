import logging
import sqlite3
import os
import re
import json
import base64
import threading
import httpx
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- KEEP-ALIVE PARA O RAILWAY ---
server = Flask('')

@server.route('/')
def home():
    return "BabaBot_26 está ativo!"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    server.run(host='0.0.0.0', port=port)

# --- CONFIGURAÇÕES ---
BOT_TOKEN = os.environ.get('BOT_TOKEN')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'leoalvesjf/telegrambot')
CONTEXT_FILE = 'context.json'

AI_MODELS = [
    "nvidia/nemotron-nano-9b-v2:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "openai/gpt-oss-20b:free",
    "openai/gpt-oss-120b:free",
]

DB_DIR = '/app/data'
DB_PATH = os.path.join(DB_DIR, 'bot.db') if os.path.exists(DB_DIR) else 'bot.db'

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- BANCO DE DADOS ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS tarefas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        descricao TEXT,
        status TEXT DEFAULT 'pendente',
        motivo_adiamento TEXT,
        criada_em TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS financeiro (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT,
        descricao TEXT,
        valor REAL,
        data TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS config (
        chave TEXT PRIMARY KEY,
        valor TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# --- HELPERS DB ---
def get_config(chave):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT valor FROM config WHERE chave = ?', (chave,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def set_config(chave, valor):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO config (chave, valor) VALUES (?, ?)', (chave, valor))
    conn.commit()
    conn.close()

def get_saldo_atual():
    saldo_inicial = float(get_config('saldo_inicial') or 0)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT SUM(CASE WHEN tipo="entrada" THEN valor ELSE -valor END) FROM financeiro')
    movimentos = cursor.fetchone()[0] or 0
    conn.close()
    return saldo_inicial + movimentos

def get_tarefas_pendentes():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, descricao, motivo_adiamento FROM tarefas WHERE status = 'pendente'")
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_ultimos_gastos(limite=5):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT tipo, descricao, valor, data FROM financeiro ORDER BY id DESC LIMIT ?', (limite,))
    rows = cursor.fetchall()
    conn.close()
    return rows

# --- GITHUB: LER E SALVAR CONTEXT.JSON ---
async def ler_context_github():
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{CONTEXT_FILE}",
                headers={
                    "Authorization": f"Bearer {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json"
                }
            )
            if response.status_code == 200:
                data = response.json()
                content = base64.b64decode(data['content']).decode('utf-8')
                return json.loads(content), data['sha']
            return {}, None
    except Exception as e:
        logging.error(f"Erro ao ler context.json: {e}")
        return {}, None

async def salvar_context_github(context_data: dict, sha: str = None):
    try:
        content = base64.b64encode(json.dumps(context_data, ensure_ascii=False, indent=2).encode()).decode()
        payload = {
            "message": f"update context - {datetime.now().strftime('%d/%m %H:%M')}",
            "content": content
        }
        if sha:
            payload["sha"] = sha
        async with httpx.AsyncClient(timeout=15) as client:
            await client.put(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{CONTEXT_FILE}",
                headers={
                    "Authorization": f"Bearer {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json"
                },
                json=payload
            )
        logging.info("✅ context.json salvo no GitHub")
    except Exception as e:
        logging.error(f"Erro ao salvar context.json: {e}")

async def atualizar_context(chave: str, valor):
    ctx, sha = await ler_context_github()
    ctx[chave] = valor
    ctx['ultima_atualizacao'] = datetime.now().strftime('%d/%m/%Y %H:%M')
    await salvar_context_github(ctx, sha)

# --- IA: CHAMAR OPENROUTER COM CONTEXTO REAL ---
async def perguntar_ia(mensagem_usuario: str, contexto_extra: str = "") -> str:
    tarefas = get_tarefas_pendentes()
    saldo = get_saldo_atual()
    meta = get_config('meta_financeira') or "não definida"
    gastos = get_ultimos_gastos()

    lista_tarefas = "\n".join([
        f"- {t[0]}. {t[1]}" + (f" (adiada porque: {t[2]})" if t[2] else "")
        for t in tarefas
    ]) or "Nenhuma tarefa pendente"

    lista_gastos = "\n".join([
        f"- {g[3]} {g[1]}: R$ {g[2]:.2f}"
        for g in gastos
    ]) or "Nenhum gasto registrado"

    ctx, _ = await ler_context_github()
    notas_pessoais = ctx.get('notas', '')
    humor_atual = ctx.get('humor', '')
    objetivos = ctx.get('objetivos', '')
    personalidade = ctx.get('personalidade', '')

    regras = personalidade if personalidade else "Maximo 3 linhas. Tom de amigo direto. Portugues informal. Nunca invente dados."

    system_prompt = (
        f"{regras}\n\n"
        f"DADOS REAIS (nao invente nada fora daqui):\n"
        f"- Tarefas pendentes: {lista_tarefas}\n"
        f"- Saldo atual: R$ {saldo:.2f}\n"
        f"- Meta financeira: R$ {meta}\n"
        f"- Ultimos gastos: {lista_gastos}\n"
        f"- Notas pessoais: {notas_pessoais or 'nenhuma'}\n"
        f"- Humor registrado: {humor_atual or 'nao registrado'}\n"
        f"- Objetivos: {objetivos or 'nao registrado'}\n"
        f"{contexto_extra}"
    )

    for model in AI_MODELS:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": mensagem_usuario}
                        ],
                        "max_tokens": 300
                    }
                )
                data = response.json()
                if 'choices' in data:
                    logging.info(f"Modelo usado: {model}")
                    return data['choices'][0]['message']['content']
        except Exception as e:
            logging.warning(f"Modelo {model} falhou: {e}")
            continue

    return "Todos os modelos estao no limite agora. Tenta em alguns minutos!"

# --- ESTADO CONVERSACIONAL ---
user_state = {}

# --- CHECKIN HORARIO ---
async def checkin_horario(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data['chat_id']
    tarefas = get_tarefas_pendentes()

    if not tarefas:
        await context.bot.send_message(
            chat_id=chat_id,
            text="*CHECK-IN*\n\nNenhuma tarefa pendente. Use /tarefa para adicionar.",
            parse_mode='Markdown'
        )
        return

    lista = "\n".join([
        f"- {t[0]}. {t[1]}" + (f" (adiada: {t[2]})" if t[2] else "")
        for t in tarefas
    ])

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"*CHECK-IN HORARIO*\n\n"
            f"Leo, tarefas pendentes:\n\n{lista}\n\n"
            f"Esta atuando em alguma? Responda *sim* ou me conta o motivo."
        ),
        parse_mode='Markdown'
    )
    user_state[chat_id] = {'aguardando': 'resposta_checkin'}

# --- COMANDOS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    context.bot_data['meu_chat_id'] = chat_id

    jobs = context.job_queue.get_jobs_by_name('checkin_horario')
    if not jobs:
        context.job_queue.run_repeating(
            checkin_horario, interval=3600, first=3600,
            data={'chat_id': chat_id}, name='checkin_horario'
        )

    saldo = get_config('saldo_inicial')
    if not saldo:
        user_state[chat_id] = {'aguardando': 'saldo_inicial'}
        await update.message.reply_text(
            "*Ola Leonardo!*\n\nQual e seu saldo atual?\n"
            "_(pode ser negativo, ex: -244.50)_",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "*Estou ativo!*\n\n"
            "/tarefa - adicionar tarefa\n"
            "/lista - ver tarefas\n"
            "/feito - concluir tarefa\n"
            "/saldo - ver saldo\n"
            "/extrato - ver lancamentos\n"
            "/nota - salvar nota pessoal\n"
            "/humor - registrar como esta se sentindo\n\n"
            "Ou fala comigo normalmente!",
            parse_mode='Markdown'
        )

async def adicionar_tarefa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Ex: /tarefa Ligar pro cliente")
        return
    tarefa = ' '.join(context.args)
    agora = datetime.now().strftime('%d/%m/%Y %H:%M')
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tarefas (descricao, criada_em) VALUES (?, ?)', (tarefa, agora))
    t_id = cursor.lastrowid
    conn.commit()
    conn.close()
    await update.message.reply_text(f"Tarefa *{t_id}* adicionada: {tarefa}", parse_mode='Markdown')

async def marcar_feita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Ex: /feito 1")
        return
    try:
        t_id = int(context.args[0])
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE tarefas SET status='concluida', motivo_adiamento=NULL WHERE id=?", (t_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Tarefa *{t_id}* concluida!", parse_mode='Markdown')
    except:
        await update.message.reply_text("Numero invalido. Use /lista.")

async def listar_tarefas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, descricao, status, motivo_adiamento FROM tarefas ORDER BY id DESC LIMIT 20')
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Nenhuma tarefa! Use /tarefa.")
        return
    texto = "*Tarefas:*\n\n"
    for r in rows:
        emoji = "OK" if r[2] == 'concluida' else "..."
        texto += f"{emoji} *{r[0]}.* {r[1]}"
        if r[3]:
            texto += f"\n   motivo: {r[3]}"
        texto += "\n"
    await update.message.reply_text(texto, parse_mode='Markdown')

async def ver_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    saldo = get_saldo_atual()
    meta = get_config('meta_financeira')
    texto = f"*Saldo atual:* R$ {saldo:.2f}"
    if meta:
        meta_f = float(meta)
        texto += f"\n*Meta:* R$ {meta_f:.2f}"
        if meta_f > 0:
            pct = (saldo / meta_f) * 100
            texto += f"\n*Progresso:* {pct:.1f}%"
    await update.message.reply_text(texto, parse_mode='Markdown')

async def ver_extrato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT tipo, descricao, valor, data FROM financeiro ORDER BY id DESC LIMIT 20')
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Nenhum lancamento ainda!\nEx: gastei 20 reais com almoco")
        return
    texto = "*Extrato:*\n\n"
    for r in rows:
        sinal = "+" if r[0] == 'entrada' else "-"
        texto += f"{sinal} {r[3]} {r[1]}: R$ {r[2]:.2f}\n"
    saldo = get_saldo_atual()
    texto += f"\n*Saldo: R$ {saldo:.2f}*"
    await update.message.reply_text(texto, parse_mode='Markdown')

async def salvar_nota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Ex: /nota preciso pagar boleto amanha")
        return
    nota = ' '.join(context.args)
    await atualizar_context('notas', nota)
    await update.message.reply_text(f"Nota salva: {nota}")

async def registrar_humor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Ex: /humor travado hoje, muito cansado")
        return
    humor = ' '.join(context.args)
    await atualizar_context('humor', f"{datetime.now().strftime('%d/%m %H:%M')} - {humor}")
    await update.message.reply_text(f"Humor registrado: {humor}")

# --- RESPOSTAS LIVRES ---
async def resposta_livre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    texto = update.message.text
    texto_lower = texto.lower()
    estado = user_state.get(chat_id, {})

    if estado.get('aguardando') == 'saldo_inicial':
        try:
            numeros = re.findall(r'-?\d+[.,]?\d*', texto)
            saldo = float(numeros[0].replace(',', '.'))
            set_config('saldo_inicial', str(saldo))
            await atualizar_context('saldo_inicial', saldo)
            user_state[chat_id] = {'aguardando': 'meta_financeira'}
            await update.message.reply_text(
                f"Saldo de *R$ {saldo:.2f}* cadastrado!\nAgora me fala sua meta financeira:",
                parse_mode='Markdown'
            )
        except:
            await update.message.reply_text("Nao entendi. Ex: -244.50 ou 1500")
        return

    if estado.get('aguardando') == 'meta_financeira':
        try:
            numeros = re.findall(r'-?\d+[.,]?\d*', texto)
            meta = float(numeros[0].replace(',', '.'))
            set_config('meta_financeira', str(meta))
            await atualizar_context('meta_financeira', meta)
            user_state[chat_id] = {}
            await update.message.reply_text(f"Meta de *R$ {meta:.2f}* definida! Estou pronto.", parse_mode='Markdown')
        except:
            await update.message.reply_text("Nao entendi. Ex: 5000")
        return

    if estado.get('aguardando') == 'resposta_checkin':
        if any(p in texto_lower for p in ['sim', 'estou', 'to', 'trabalhando', 'fazendo']):
            user_state[chat_id] = {}
            await update.message.reply_text("Otimo! Foco total.")
        else:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("UPDATE tarefas SET motivo_adiamento=? WHERE status='pendente'", (texto,))
            conn.commit()
            conn.close()
            await atualizar_context('ultimo_motivo_adiamento', texto)
            user_state[chat_id] = {}
            resposta = await perguntar_ia(
                texto,
                contexto_extra=f"Leonardo nao esta conseguindo trabalhar porque: {texto}. Responda em no maximo 2 linhas."
            )
            await update.message.reply_text(f"Anotei.\n\n{resposta}")
        return

    palavras_saida = ['gastei', 'paguei', 'comprei', 'debitou', 'saiu']
    palavras_entrada = ['recebi', 'entrou', 'ganhei', 'depositei']
    tipo = None
    for p in palavras_saida:
        if p in texto_lower:
            tipo = 'saida'
            break
    for p in palavras_entrada:
        if p in texto_lower:
            tipo = 'entrada'
            break

    numeros = re.findall(r'\d+[.,]?\d*', texto)
    if tipo and numeros:
        valor = float(numeros[0].replace(',', '.'))
        agora = datetime.now().strftime('%d/%m %H:%M')
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO financeiro (tipo, descricao, valor, data) VALUES (?, ?, ?, ?)',
                      (tipo, texto, valor, agora))
        conn.commit()
        conn.close()
        saldo = get_saldo_atual()
        await atualizar_context('ultimo_lancamento', f"{agora} - {texto}: R$ {valor:.2f}")
        sinal = "-" if tipo == 'saida' else "+"
        await update.message.reply_text(
            f"{sinal} R$ {valor:.2f} lancado!\nSaldo: *R$ {saldo:.2f}*",
            parse_mode='Markdown'
        )
        return

    await update.message.reply_text("...")
    resposta = await perguntar_ia(texto)
    await update.message.reply_text(resposta)

def main():
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tarefa", adicionar_tarefa))
    app.add_handler(CommandHandler("lista", listar_tarefas))
    app.add_handler(CommandHandler("feito", marcar_feita))
    app.add_handler(CommandHandler("saldo", ver_saldo))
    app.add_handler(CommandHandler("extrato", ver_extrato))
    app.add_handler(CommandHandler("nota", salvar_nota))
    app.add_handler(CommandHandler("humor", registrar_humor))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, resposta_livre))

    logging.info("BabaBot_26 operacional!")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
