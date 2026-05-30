import asyncio
from sqlalchemy import text
from app.database import engine

async def clear():
    async with engine.begin() as conn:
        # TRUNCATE CASCADE will delete all triage_sessions and cascade down to 
        # all messages, facts, and audit logs associated with those sessions.
        print("Clearing all chat history from the database...")
        await conn.execute(text("TRUNCATE TABLE triage_sessions CASCADE;"))
        print("All chat history cleared successfully!")

if __name__ == "__main__":
    asyncio.run(clear())
