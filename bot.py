import logging
import sqlite3
import os
from datetime import time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# CONFIGURAÇÕES
BOT_TOKEN = os.environ.get('BOT_TOKEN')
DB_DIR = '/app/data'
DB_PATH = os.path.join(DB_DIR, 'tarefas.db') if os.path.exists(DB_DIR) else 'tarefas.db'

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS tarefas 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, descricao TEXT, status TEXT DEFAULT 'pendente')''')
    conn.commit()
    conn.close()

init_db()

# FUNÇÃO QUE RODA SOZINHA (O CUTUCÃO)
async def cobranca_automatica(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    t_id, t_nome, chat_id = job.data['id'], job.data['tarefa'], job.data['chat_id']
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM tarefas WHERE id = ?', (t_id,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0] != 'concluida':
        logging.info(f"🔔 Enviando cobrança ativa para tarefa {t_id}")
        await context.bot.send_message(chat_id=chat_id, 
            text=f"🔔 *CHECK-IN DE FOCO*\n\nLeo, ainda está em: *{t_nome}*?\n\nTerminou? `/feito {t_id}`\nSenão, volta pra cá! ⚓",
            parse_mode='Markdown')

# COMANDOS
async def adicionar_tarefa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    tarefa = ' '.join(context.args)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tarefas (descricao) VALUES (?)', (tarefa,))
    t_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Agendando 30 segundos para o teste de fogo
    context.job_queue.run_once(cobranca_automatica, when=30, 
                               data={'chat_id': update.effective_chat.id, 'tarefa': tarefa, 'id': t_id})
    
    await update.message.reply_text(f"✅ Gravado: *{tarefa}*\n⏳ Ativei meu cronômetro interno. Te chamo em 30s!", parse_mode='Markdown')

async def listar_tarefas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, descricao, status FROM tarefas')
    rows = cursor.fetchall()
    conn.close()
    res = "📋 *Tarefas:*\n" + "\n".join([f"{'✅' if r[2]=='concluida' else '⏳'} {r[0]}. {r[1]}" for r in rows])
    await update.message.reply_text(res or "Vazio", parse_mode='Markdown')

async def marcar_feita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        t_id = int(context.args[0])
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE tarefas SET status = 'concluida' WHERE id = ?", (t_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🎉 Boa, Leo! Foco mantido.")
    except: pass

def main():
    # drop_pending_updates limpa o "lixo" acumulado ao reiniciar
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("tarefa", adicionar_tarefa))
    app.add_handler(CommandHandler("lista", listar_tarefas))
    app.add_handler(CommandHandler("feito", marcar_feita))

    print("🤖 BabaBot_26 Iniciado com JobQueue...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()