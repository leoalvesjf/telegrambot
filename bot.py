import logging
import sqlite3
import os
from datetime import time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ============================================================
# CONFIGURAÇÕES E BANCO DE DADOS PERSISTENTE
# ============================================================

BOT_TOKEN = os.environ.get('BOT_TOKEN')

# Caminho para o Volume do Railway
DB_DIR = '/app/data'
DB_PATH = os.path.join(DB_DIR, 'tarefas.db') if os.path.exists(DB_DIR) else 'tarefas.db'

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tarefas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            status TEXT DEFAULT 'pendente'
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ============================================================
# FUNÇÕES DE AGENDAMENTO (ÂNCORA)
# ============================================================

async def cobranca_automatica(context: ContextTypes.DEFAULT_TYPE):
    """Esta função roda sozinha quando o timer acaba"""
    job = context.job
    tarefa_id = job.data['id']
    tarefa_nome = job.data['tarefa']
    chat_id = job.data['chat_id']

    logging.info(f"🤖 Verificando tarefa {tarefa_id} automaticamente...")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM tarefas WHERE id = ?', (tarefa_id,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0] != 'concluida':
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔔 *CHECK-IN DE FOCO*\n\n"
                 f"Leo, ainda está focado em: *{tarefa_nome}*?\n\n"
                 f"Se terminou: `/feito {tarefa_id}`\n"
                 f"Se dispersou, volta pra cá! ⚓",
            parse_mode='Markdown'
        )

async def bom_dia(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.bot_data.get('meu_chat_id')
    if chat_id:
        await context.bot.send_message(chat_id=chat_id, text="☀️ *Bom dia, Leonardo!*\nQual a meta única de hoje?", parse_mode='Markdown')

async def boa_noite(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.bot_data.get('meu_chat_id')
    if chat_id:
        await context.bot.send_message(chat_id=chat_id, text="🌙 *Dia encerrado.*\nComo foi o progresso hoje?", parse_mode='Markdown')

# ============================================================
# COMANDOS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.bot_data['meu_chat_id'] = update.effective_chat.id
    await update.message.reply_text("👋 Leonardo pronto! Memória e cobrança ativa. 💾")

async def adicionar_tarefa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Diga a tarefa. Ex: /tarefa Revisar Upwork")
        return

    tarefa = ' '.join(context.args)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tarefas (descricao) VALUES (?)', (tarefa,))
    tarefa_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # AGENDA COBRANÇA AUTOMÁTICA (45 segundos para teste)
    context.job_queue.run_once(
        cobranca_automatica, 
        when=45, 
        data={'chat_id': update.effective_chat.id, 'tarefa': tarefa, 'id': tarefa_id}
    )

    await update.message.reply_text(f"✅ Gravado: *{tarefa}*\n⏳ Te chamo em 45s!")

async def listar_tarefas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, descricao, status FROM tarefas')
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Lista vazia.")
        return
    texto = "📋 *Tarefas:* \n\n"
    for row in rows:
        emoji = "✅" if row[2] == 'concluida' else "⏳"
        texto += f"{emoji} {row[0]}. {row[1]}\n"
    await update.message.reply_text(texto, parse_mode='Markdown')

async def marcar_feita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tarefa_id = int(context.args[0])
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE tarefas SET status = 'concluida' WHERE id = ?", (tarefa_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🎉 Boa, Leo!")
    except:
        await update.message.reply_text("Número inválido.")

async def resposta_livre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Para salvar: /tarefa + texto")

# ============================================================
# MAIN
# ============================================================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tarefa", adicionar_tarefa))
    app.add_handler(CommandHandler("lista", listar_tarefas))
    app.add_handler(CommandHandler("feito", marcar_feita))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, resposta_livre))

    # Inicia agendamentos diários
    if app.job_queue:
        app.job_queue.run_daily(bom_dia, time=time(10, 0))   
        app.job_queue.run_daily(boa_noite, time=time(1, 0))  

    print(f"🤖 BabaBot_26 Ativo | Banco: {DB_PATH}")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()