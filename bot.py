import logging
import sqlite3
import os
import re
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
AI_MODEL = "qwen/qwen3-next-80b-a3b-instruct:free"

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

# --- IA: CHAMAR OPENROUTER ---
async def perguntar_ia(mensagem_usuario: str, contexto_extra: str = "") -> str:
    tarefas = get_tarefas_pendentes()
    saldo = get_saldo_atual()
    meta = get_config('meta_financeira') or "não definida"

    lista_tarefas = "\n".join([f"- {t[0]}. {t[1]}" + (f" (adiada: {t[2]})" if t[2] else "") for t in tarefas]) or "Nenhuma tarefa pendente"

    system_prompt = f"""Você é o assistente pessoal do Leonardo, um engenheiro de software com TDAH.
Você é seu secretário, parceiro e apoio emocional.

CONTEXTO ATUAL:
- Tarefas pendentes: {lista_tarefas}
- Saldo atual: R$ {saldo:.2f}
- Meta financeira: R$ {meta}
{contexto_extra}

COMO VOCÊ AGE:
- Respostas curtas e diretas — nunca mais de 3 parágrafos
- Tom humano, caloroso, sem ser fake
- Foca em UMA coisa por vez
- Quando ele estiver travado, sugere o menor passo possível
- Nunca julga, sempre encoraja
- Lembra que ele tem TDAH e precisa de estrutura externa
- Responde sempre em português brasileiro"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": AI_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": mensagem_usuario}
                    ],
                    "max_tokens": 500
                }
            )
            data = response.json()
            return data['choices'][0]['message']['content']
    except Exception as e:
        logging.error(f"Erro na IA: {e}")
        return "Tive um probleminha pra pensar agora 😅 Tenta de novo em instantes!"

# --- ESTADO CONVERSACIONAL ---
user_state = {}

# --- CHECKIN HORÁRIO ---
async def checkin_horario(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data['chat_id']
    tarefas = get_tarefas_pendentes()

    if not tarefas:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ *CHECK-IN HORÁRIO*\n\nNenhuma tarefa pendente!\nUse /tarefa para adicionar algo.",
            parse_mode='Markdown'
        )
        return

    lista = "\n".join([f"• {t[0]}. {t[1]}" + (f"\n  ↳ _adiada: {t[2]}_" if t[2] else "") for t in tarefas])

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏰ *CHECK-IN HORÁRIO*\n\n"
            f"Leo, suas tarefas pendentes:\n\n{lista}\n\n"
            f"Está atuando em alguma agora?\n"
            f"Responda *sim* ou me conta o que está te impedindo."
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
            checkin_horario,
            interval=3600,
            first=3600,
            data={'chat_id': chat_id},
            name='checkin_horario'
        )

    saldo = get_config('saldo_inicial')
    if not saldo:
        user_state[chat_id] = {'aguardando': 'saldo_inicial'}
        await update.message.reply_text(
            "👋 *Olá Leonardo!*\n\n"
            "Para começar, me diz:\n"
            "*Qual é o seu saldo atual em reais?*\n\nEx: `1500.00`",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "👋 *Leonardo, estou ativo!*\n\n"
            "📌 /tarefa — adicionar tarefa\n"
            "📋 /lista — ver tarefas\n"
            "✅ /feito — concluir tarefa\n"
            "💰 /saldo — ver saldo atual\n"
            "📊 /extrato — ver lançamentos\n\n"
            "Ou fala comigo normalmente! Estou aqui. 💙",
            parse_mode='Markdown'
        )

async def adicionar_tarefa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Me fala a tarefa! Ex: /tarefa Ligar pro cliente")
        return
    tarefa = ' '.join(context.args)
    agora = datetime.now().strftime('%d/%m/%Y %H:%M')
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tarefas (descricao, criada_em) VALUES (?, ?)', (tarefa, agora))
    t_id = cursor.lastrowid
    conn.commit()
    conn.close()
    await update.message.reply_text(
        f"✅ Tarefa *{t_id}* adicionada:\n📌 {tarefa}\n\nTe cobro no próximo check-in! ⏰",
        parse_mode='Markdown'
    )

async def marcar_feita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Me fala o número! Ex: /feito 1")
        return
    try:
        t_id = int(context.args[0])
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE tarefas SET status='concluida', motivo_adiamento=NULL WHERE id=?", (t_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🎉 Arrasou, Leo! Tarefa *{t_id}* concluída!", parse_mode='Markdown')
    except:
        await update.message.reply_text("Número inválido. Use /lista.")

async def listar_tarefas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, descricao, status, motivo_adiamento FROM tarefas ORDER BY id DESC LIMIT 20')
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Nenhuma tarefa ainda! Use /tarefa.")
        return
    texto = "📋 *Suas tarefas:*\n\n"
    for r in rows:
        emoji = "✅" if r[2] == 'concluida' else "⏳"
        texto += f"{emoji} *{r[0]}.* {r[1]}"
        if r[3]:
            texto += f"\n   ↳ _adiada: {r[3]}_"
        texto += "\n"
    await update.message.reply_text(texto, parse_mode='Markdown')

async def ver_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    saldo = get_saldo_atual()
    meta = get_config('meta_financeira')
    texto = f"💰 *Saldo atual:* R$ {saldo:.2f}"
    if meta:
        texto += f"\n🎯 *Meta:* R$ {float(meta):.2f}"
        pct = (saldo / float(meta)) * 100
        texto += f"\n📈 *Progresso:* {pct:.1f}%"
    await update.message.reply_text(texto, parse_mode='Markdown')

async def ver_extrato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT tipo, descricao, valor, data FROM financeiro ORDER BY id DESC LIMIT 20')
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Nenhum lançamento ainda!\nEx: _'gastei 20 reais com almoço'_", parse_mode='Markdown')
        return
    texto = "📊 *Extrato:*\n\n"
    for r in rows:
        emoji = "📈" if r[0] == 'entrada' else "📉"
        texto += f"{emoji} {r[3]} — {r[1]}: *R$ {r[2]:.2f}*\n"
    saldo = get_saldo_atual()
    texto += f"\n💰 *Saldo atual: R$ {saldo:.2f}*"
    await update.message.reply_text(texto, parse_mode='Markdown')

# --- RESPOSTAS LIVRES COM IA ---
async def resposta_livre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    texto = update.message.text
    texto_lower = texto.lower()
    estado = user_state.get(chat_id, {})

    # --- FLUXO: saldo inicial ---
    if estado.get('aguardando') == 'saldo_inicial':
        try:
            numeros = re.findall(r'\d+[.,]?\d*', texto)
            saldo = float(numeros[0].replace(',', '.'))
            set_config('saldo_inicial', str(saldo))
            user_state[chat_id] = {'aguardando': 'meta_financeira'}
            await update.message.reply_text(
                f"✅ Saldo de *R$ {saldo:.2f}* cadastrado!\n\nAgora me fala sua *meta financeira*.\nEx: `5000.00`",
                parse_mode='Markdown'
            )
        except:
            await update.message.reply_text("Não entendi. Manda só o número. Ex: `1500.00`", parse_mode='Markdown')
        return

    # --- FLUXO: meta financeira ---
    if estado.get('aguardando') == 'meta_financeira':
        try:
            numeros = re.findall(r'\d+[.,]?\d*', texto)
            meta = float(numeros[0].replace(',', '.'))
            set_config('meta_financeira', str(meta))
            user_state[chat_id] = {}
            await update.message.reply_text(
                f"🎯 Meta de *R$ {meta:.2f}* definida!\n\nAgora pode falar comigo normalmente. Estou aqui! 💙",
                parse_mode='Markdown'
            )
        except:
            await update.message.reply_text("Não entendi. Manda só o número. Ex: `5000.00`", parse_mode='Markdown')
        return

    # --- FLUXO: resposta do checkin ---
    if estado.get('aguardando') == 'resposta_checkin':
        if any(p in texto_lower for p in ['sim', 'estou', 'tô', 'to', 'trabalhando', 'fazendo']):
            user_state[chat_id] = {}
            await update.message.reply_text("💪 Ótimo! Foco total. Te checo na próxima hora!")
        else:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("UPDATE tarefas SET motivo_adiamento=? WHERE status='pendente'", (texto,))
            conn.commit()
            conn.close()
            user_state[chat_id] = {}

            # IA responde ao motivo com empatia
            resposta = await perguntar_ia(
                texto,
                contexto_extra=f"Leonardo acabou de dizer que não está conseguindo trabalhar nas tarefas porque: {texto}. Responda com empatia e sugira um pequeno passo."
            )
            await update.message.reply_text(f"📝 Motivo anotado.\n\n{resposta}")
        return

    # --- LANÇAMENTO FINANCEIRO ---
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
        emoji = "📉" if tipo == 'saida' else "📈"
        await update.message.reply_text(
            f"{emoji} Lançado: *R$ {valor:.2f}*\n💰 Saldo atual: *R$ {saldo:.2f}*",
            parse_mode='Markdown'
        )
        return

    # --- IA RESPONDE TUDO MAIS ---
    await update.message.reply_text("⏳ Pensando...")
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, resposta_livre))

    logging.info("🤖 BabaBot_26 com IA integrada — Operacional!")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
