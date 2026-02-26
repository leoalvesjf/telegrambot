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

# AJUSTE PARA O VOLUME DO RAILWAY
# Se a pasta /app/data existir (no Railway), salva lá. Se não, salva local (tarefas.db).
DB_DIR = '/app/data'
DB_PATH = os.path.join(DB_DIR, 'tarefas.db') if os.path.exists(DB_DIR) else 'tarefas.db'

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

def init_db():
    """Cria o banco de dados e a tabela se não existirem"""
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

# Inicializa o banco ao rodar o script
init_db()

# ============================================================
# COMANDOS DO TELEGRAM
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Primeiro contato — Boas-vindas"""
    chat_id = update.effective_chat.id
    context.bot_data['meu_chat_id'] = chat_id 

    await update.message.reply_text(
        "👋 Fala, Leonardo! Memória definitiva ativada. 💾\n\n"
        "Com o Volume do Railway, suas tarefas não somem mais no deploy.\n\n"
        "📌 /tarefa — adicionar uma tarefa\n"
        "📋 /lista — ver suas tarefas\n"
        "✅ /feito — marcar tarefa como concluída (ex: /feito 1)\n\n"
        "Qual é a sua prioridade agora?",
        parse_mode='Markdown'
    )

async def adicionar_tarefa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Salva a tarefa no SQLite (dentro do Volume)"""
    if not context.args:
        await update.message.reply_text("Me fala a tarefa! Ex: /tarefa Prospectar Upwork")
        return

    tarefa = ' '.join(context.args)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tarefas (descricao) VALUES (?)', (tarefa,))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ Gravado com segurança:\n📌 *{tarefa}*", parse_mode='Markdown')

async def listar_tarefas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Busca tarefas no banco persistente e exibe"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, descricao, status FROM tarefas')
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("Sua lista está limpa!")
        return

    texto = "📋 *Tarefas Guardadas:* \n\n"
    for row in rows:
        emoji = "✅" if row[2] == 'concluida' else "⏳"
        texto += f"{emoji} {row[0]}. {row[1]}\n"

    texto += "\nPara concluir: `/feito ID`"
    await update.message.reply_text(texto, parse_mode='Markdown')

async def marcar_feita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Atualiza o status no banco"""
    if not context.args:
        await update.message.reply_text("Me fala o número da tarefa! Ex: /feito 1")
        return

    try:
        tarefa_id = int(context.args[0])
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE tarefas SET status = 'concluida' WHERE id = ?", (tarefa_id,))
        conn.commit()
        
        if cursor.rowcount > 0:
            await update.message.reply_text(f"🎉 Boa, Leo! Tarefa {tarefa_id} concluída!")
        else:
            await update.message.reply_text("Não achei nenhuma tarefa com esse número.")
        
        conn.close()
    except ValueError:
        await update.message.reply_text("Mande apenas o número (ID) da tarefa.")

async def resposta_livre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Encorajamento para TDAH"""
    texto = update.message.text.lower()
    gatilhos = ['não consigo', 'nao consigo', 'desisti', 'cansado', 'travado']

    if any(p in texto for p in gatilhos):
        await update.message.reply_text(
            "Ei... respira. 💙\n\nO TDAH às vezes trava a gente. Qual o *menor passo* agora?",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("Recebi! 📝 Para salvar: /tarefa " + update.message.text)

# ============================================================
# EXECUÇÃO
# ============================================================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tarefa", adicionar_tarefa))
    app.add_handler(CommandHandler("lista", listar_tarefas))
    app.add_handler(CommandHandler("feito", marcar_feita))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, resposta_livre))

    # Agendamentos (Horário de Brasília)
    job_queue = app.job_queue
    job_queue.run_daily(bom_dia, time=time(10, 0))   
    job_queue.run_daily(boa_noite, time=time(1, 0))  

    print(f"🤖 Bot rodando! Banco em: {DB_PATH}")
    app.run_polling()

if __name__ == '__main__':
    main()