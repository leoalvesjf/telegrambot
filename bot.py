import logging
import sqlite3
import os
import threading
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
DB_DIR = '/app/data'
DB_PATH = os.path.join(DB_DIR, 'tarefas.db') if os.path.exists(DB_DIR) else 'tarefas.db'

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS tarefas 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      descricao TEXT, 
                      status TEXT DEFAULT 'pendente')''')
    conn.commit()
    conn.close()

init_db()

# --- AGENDADOR ---
async def cobranca_automatica(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    t_id = job.data['id']
    t_nome = job.data['tarefa']
    chat_id = job.data['chat_id']

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM tarefas WHERE id = ?', (t_id,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0] != 'concluida':
        logging.info(f"🔔 Enviando cobrança para tarefa {t_id}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🔔 *CHECK-IN DE FOCO*\n\n"
                f"Leo, ainda estás em: *{t_nome}*?\n\n"
                f"Terminou? Use `/feito {t_id}`\n"
                f"Senão, volta o foco! ⚓"
            ),
            parse_mode='Markdown'
        )
    else:
        job.schedule_removal()

# --- COMANDOS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.bot_data['meu_chat_id'] = update.effective_chat.id
    await update.message.reply_text(
        "👋 *Leonardo, estou ativo!*\n\n"
        "Comandos disponíveis:\n"
        "📌 /tarefa — adicionar uma tarefa\n"
        "📋 /lista — ver suas tarefas\n"
        "✅ /feito — marcar tarefa como concluída\n\n"
        "Me manda uma tarefa e eu fico de olho pra você! 💙",
        parse_mode='Markdown'
    )

async def adicionar_tarefa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Me fala a tarefa! Ex: /tarefa Ligar pro cliente")
        return

    tarefa = ' '.join(context.args)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tarefas (descricao) VALUES (?)', (tarefa,))
    t_id = cursor.lastrowid
    conn.commit()
    conn.close()

    context.job_queue.run_repeating(
        cobranca_automatica,
        interval=20,
        first=20,
        data={'chat_id': update.effective_chat.id, 'tarefa': tarefa, 'id': t_id},
        name=f'tarefa_{t_id}'
    )

    await update.message.reply_text(
        f"✅ Gravado: *{tarefa}*\n"
        f"⏳ Vou te lembrar a cada 20 segundos até concluir!\n"
        f"Quando terminar: `/feito {t_id}`",
        parse_mode='Markdown'
    )

async def marcar_feita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Me fala o número da tarefa! Ex: /feito 1")
        return

    try:
        t_id = int(context.args[0])

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE tarefas SET status = 'concluida' WHERE id = ?", (t_id,))
        conn.commit()
        conn.close()

        jobs = context.job_queue.get_jobs_by_name(f'tarefa_{t_id}')
        for job in jobs:
            job.schedule_removal()

        await update.message.reply_text(f"🎉 Arrasou, Leo! Tarefa {t_id} concluída!")

    except (ValueError, IndexError):
        await update.message.reply_text("Número inválido. Use /lista pra ver os números.")

async def listar_tarefas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, descricao, status FROM tarefas')
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("Nenhuma tarefa ainda! Use /tarefa para adicionar.")
        return

    texto = "📋 *Suas tarefas:*\n\n"
    for r in rows:
        emoji = "✅" if r[2] == 'concluida' else "⏳"
        texto += f"{emoji} {r[0]}. {r[1]}\n"

    texto += "\nPara concluir: `/feito <número>`"
    await update.message.reply_text(texto, parse_mode='Markdown')

async def resposta_livre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.lower()
    if any(p in texto for p in ['não consigo', 'nao consigo', 'travado', 'desisti', 'cansado']):
        await update.message.reply_text(
            "Ei, respira. 💙\n\n"
            "Só uma coisa. Qual é o menor passo possível agora?"
        )
    else:
        await update.message.reply_text(
            f"Quer adicionar isso como tarefa?\n`/tarefa {update.message.text}`",
            parse_mode='Markdown'
        )

def main():
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tarefa", adicionar_tarefa))
    app.add_handler(CommandHandler("lista", listar_tarefas))
    app.add_handler(CommandHandler("feito", marcar_feita))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, resposta_livre))

    logging.info("🤖 BabaBot_26 Operacional!")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()