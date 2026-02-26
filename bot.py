import logging
from datetime import time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import BOT_TOKEN

# Log para debug
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# ============================================================
# COMANDOS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Primeiro contato — salva o chat_id do usuário"""
    chat_id = update.effective_chat.id
    context.bot_data['meu_chat_id'] = chat_id  # salva pra usar nos lembretes

    await update.message.reply_text(
        "👋 Oi! Eu sou seu secretário pessoal!\n\n"
        "Todo dia às *7h da manhã* eu te mando uma mensagem perguntando qual é sua prioridade do dia.\n"
        "Todo dia às *22h* eu checo como foi.\n\n"
        "Você também pode falar comigo a qualquer hora! Tente:\n"
        "📌 /tarefa — adicionar uma tarefa\n"
        "📋 /lista — ver suas tarefas\n"
        "✅ /feito — marcar tarefa como concluída\n\n"
        "Bora começar? Me conta: *qual é a coisa mais importante que você precisa fazer hoje?*",
        parse_mode='Markdown'
    )

async def adicionar_tarefa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adiciona uma tarefa à lista"""
    if not context.args:
        await update.message.reply_text("Me fala a tarefa! Ex: /tarefa Ligar pro cliente")
        return

    tarefa = ' '.join(context.args)

    if 'tarefas' not in context.user_data:
        context.user_data['tarefas'] = []

    context.user_data['tarefas'].append({'texto': tarefa, 'feita': False})

    await update.message.reply_text(f"✅ Tarefa adicionada:\n📌 *{tarefa}*", parse_mode='Markdown')

async def listar_tarefas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista todas as tarefas"""
    tarefas = context.user_data.get('tarefas', [])

    if not tarefas:
        await update.message.reply_text("Você não tem tarefas ainda! Use /tarefa para adicionar.")
        return

    texto = "📋 *Suas tarefas:*\n\n"
    for i, t in enumerate(tarefas):
        emoji = "✅" if t['feita'] else "⏳"
        texto += f"{emoji} {i+1}. {t['texto']}\n"

    texto += "\nPara marcar como feita: /feito 1 (ou o número da tarefa)"
    await update.message.reply_text(texto, parse_mode='Markdown')

async def marcar_feita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Marca uma tarefa como concluída"""
    tarefas = context.user_data.get('tarefas', [])

    if not context.args:
        await update.message.reply_text("Me fala o número da tarefa! Ex: /feito 1")
        return

    try:
        num = int(context.args[0]) - 1
        tarefas[num]['feita'] = True
        context.user_data['tarefas'] = tarefas
        await update.message.reply_text(f"🎉 Arrasou! Tarefa *{num+1}* concluída!", parse_mode='Markdown')
    except (IndexError, ValueError):
        await update.message.reply_text("Número inválido. Use /lista pra ver os números.")

async def resposta_livre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde mensagens livres com encorajamento"""
    texto = update.message.text.lower()

    if any(p in texto for p in ['não consigo', 'nao consigo', 'desisti', 'cansado', 'travado']):
        await update.message.reply_text(
            "Ei... respira. 💙\n\n"
            "Você não precisa fazer tudo agora. Só *uma coisa*.\n"
            "Qual é a menor tarefa possível que você consegue fazer nos próximos 10 minutos?",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "Recebi! 📝\n\nQuer que eu adicione isso como tarefa? Se sim, use:\n/tarefa " + update.message.text
        )

# ============================================================
# MENSAGENS AUTOMÁTICAS (agendadas)
# ============================================================

async def bom_dia(context: ContextTypes.DEFAULT_TYPE):
    """Mensagem automática de manhã"""
    chat_id = context.bot_data.get('meu_chat_id')
    if not chat_id:
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "☀️ *Bom dia!*\n\n"
            "Novo dia, nova chance.\n\n"
            "👉 Me fala: *qual é a UMA coisa mais importante que você precisa fazer hoje?*\n\n"
            "_(Só uma. O resto é bônus.)_"
        ),
        parse_mode='Markdown'
    )

async def boa_noite(context: ContextTypes.DEFAULT_TYPE):
    """Mensagem automática à noite"""
    chat_id = context.bot_data.get('meu_chat_id')
    if not chat_id:
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "🌙 *Como foi o dia?*\n\n"
            "Conseguiu fazer a tarefa principal?\n\n"
            "Me conta — mesmo que não tenha conseguido, tudo bem. "
            "O importante é não desistir. 💙\n\n"
            "Use /lista pra ver suas tarefas pendentes."
        ),
        parse_mode='Markdown'
    )

# ============================================================
# MAIN
# ============================================================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tarefa", adicionar_tarefa))
    app.add_handler(CommandHandler("lista", listar_tarefas))
    app.add_handler(CommandHandler("feito", marcar_feita))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, resposta_livre))

    # Agendamentos automáticos (horário de Brasília = UTC-3)
    job_queue = app.job_queue
    job_queue.run_daily(bom_dia, time=time(10, 0))   # 7h Brasília = 10h UTC
    job_queue.run_daily(boa_noite, time=time(1, 0))  # 22h Brasília = 01h UTC

    print("🤖 Bot rodando! Vá no Telegram e mande /start pro seu bot.")
    app.run_polling()

if __name__ == '__main__':
    main()
