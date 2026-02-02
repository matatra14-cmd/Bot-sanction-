
import discord
from discord import Option
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from typing import List, Optional
import os

# Récupérer le token depuis Railway
TOKEN = os.getenv('TOKEN')
if not TOKEN:
    raise ValueError("❌ La variable d'environnement TOKEN n'est pas définie sur Railway")

# Configuration des raisons prédéfinies
PREDEFINED_REASONS = {
    "tempmute": [
        "Spam",
        "Langage inapproprié", 
        "Publicité non autorisée",
        "Harcèlement",
        "Contenu NSFW"
    ],
    "timeout": [
        "Comportement toxique",
        "Dérangement volontaire",
        "Non-respect des règles",
        "Insultes répétées"
    ]
}

# Durées prédéfinies pour tempmute (en secondes)
TEMPMUTE_DURATIONS = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "1j": 86400,
    "3j": 259200,
    "7j": 604800
}

# Durées prédéfinies pour timeout
TIMEOUT_DURATIONS = {
    "5m": 300,
    "1h": 3600,
    "1j": 86400,
    "3j": 259200,
    "1sem": 604800
}

class Sanction:
    def __init__(self, user_id: int, moderator_id: int, reason: str, sanction_type: str, duration: Optional[int] = None):
        self.id = 0
        self.user_id = user_id
        self.moderator_id = moderator_id
        self.reason = reason
        self.type = sanction_type
        self.duration = duration
        self.date = datetime.now()
        self.expired = False

# Base de données en mémoire
class SanctionsDB:
    def __init__(self):
        self.tempmutes = []
        self.timeouts = []
        self.bans = []
        self.warns = []
        self.counters = {"tempmute": 0, "timeout": 0, "warn": 0}
    
    def add_sanction(self, sanction: Sanction):
        if sanction.type == "tempmute":
            self.counters["tempmute"] += 1
            sanction.id = self.counters["tempmute"]
            self.tempmutes.append(sanction)
        elif sanction.type == "timeout":
            self.counters["timeout"] += 1
            sanction.id = self.counters["timeout"]
            self.timeouts.append(sanction)
        elif sanction.type == "ban":
            sanction.id = len(self.bans) + 1
            self.bans.append(sanction)
        elif sanction.type == "warn":
            self.counters["warn"] += 1
            sanction.id = self.counters["warn"]
            self.warns.append(sanction)
    
    def get_user_sanctions(self, user_id: int):
        return {
            "tempmutes": [s for s in self.tempmutes if s.user_id == user_id and not s.expired],
            "timeouts": [s for s in self.timeouts if s.user_id == user_id and not s.expired],
            "bans": [s for s in self.bans if s.user_id == user_id],
            "warns": [s for s in self.warns if s.user_id == user_id]
        }
    
    def delete_user_sanctions(self, user_id: int):
        self.tempmutes = [s for s in self.tempmutes if s.user_id != user_id]
        self.timeouts = [s for s in self.timeouts if s.user_id != user_id]
        self.bans = [s for s in self.bans if s.user_id != user_id]
        self.warns = [s for s in self.warns if s.user_id != user_id]

sanctions_db = SanctionsDB()

class SanctionsView(discord.ui.View):
    def __init__(self, user: discord.User, tempmutes: List, timeouts: List, bans: List, moderator: discord.Member):
        super().__init__(timeout=60)
        self.user = user
        self.tempmutes = tempmutes
        self.timeouts = timeouts
        self.bans = bans
        self.moderator = moderator
        self.current_page = 0
        self.current_type = "tempmutes"
        self.update_buttons()
    
    def update_buttons(self):
        self.clear_items()
        
        # Bouton précédent
        prev_btn = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji="⬅️", disabled=self.current_page == 0)
        prev_btn.callback = self.previous_page
        self.add_item(prev_btn)
        
        # Boutons de type
        types = ["tempmutes", "timeouts", "bans"]
        for type_name in types:
            btn = discord.ui.Button(
                style=discord.ButtonStyle.primary if self.current_type == type_name else discord.ButtonStyle.secondary,
                label=type_name.capitalize(),
                disabled=self.current_type == type_name
            )
            btn.callback = lambda i, t=type_name: self.switch_type(i, t)
            self.add_item(btn)
        
        # Bouton suivant
        total_items = len(getattr(self, self.current_type))
        next_btn = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji="➡️", 
                                   disabled=(self.current_page + 1) * 10 >= total_items)
        next_btn.callback = self.next_page
        self.add_item(next_btn)
    
    async def create_embed(self):
        if self.current_type == "tempmutes":
            title = "🔇 Sanction de"
            color = discord.Color.from_str("#FFFFFF")
            items = self.tempmutes
            sanction_name = "Tempmute"
        elif self.current_type == "timeouts":
            title = "⏰ Sanction de"
            color = discord.Color.from_str("#FFFFFF")
            items = self.timeouts
            sanction_name = "TO"
        else:  # bans
            title = "🔨 Sanction de"
            color = discord.Color.from_str("#FFFFFF")
            items = self.bans
            sanction_name = "Ban"
        
        embed = discord.Embed(
            title=f"{title} {self.user.name}",
            color=color,
            timestamp=datetime.now()
        )
        
        start_idx = self.current_page * 10
        end_idx = min(start_idx + 10, len(items))
        
        for i in range(start_idx, end_idx):
            sanction = items[i]
            moderator = self.moderator.guild.get_member(sanction.moderator_id)
            moderator_name = moderator.mention if moderator else f"ID: {sanction.moderator_id}"
            
            field_value = f"**{sanction_name} #{sanction.id}**\n"
            field_value += f"> {sanction_name.lower()} pour {sanction.reason} par {moderator_name} le <t:{int(sanction.date.timestamp())}:F>"
            
            if sanction.duration:
                expire_time = sanction.date + timedelta(seconds=sanction.duration)
                field_value += f"\n> Durée: {self.format_duration(sanction.duration)} (expire <t:{int(expire_time.timestamp())}:R>)"
            
            embed.add_field(name="\u200b", value=field_value, inline=False)
        
        total_pages = (len(items) + 9) // 10
        embed.set_footer(text=f"Page {self.current_page + 1}/{max(1, total_pages)} • {len(items)} sanction(s)")
        
        return embed
    
    def format_duration(self, seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m"
        elif seconds < 86400:
            return f"{seconds // 3600}h"
        else:
            return f"{seconds // 86400}j"
    
    async def previous_page(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.current_page -= 1
        self.update_buttons()
        embed = await self.create_embed()
        await interaction.edit_original_response(embed=embed, view=self)
    
    async def next_page(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.current_page += 1
        self.update_buttons()
        embed = await self.create_embed()
        await interaction.edit_original_response(embed=embed, view=self)
    
    async def switch_type(self, interaction: discord.Interaction, type_name: str):
        await interaction.response.defer()
        self.current_type = type_name
        self.current_page = 0
        self.update_buttons()
        embed = await self.create_embed()
        await interaction.edit_original_response(embed=embed, view=self)

class DeleteSanctionsView(discord.ui.View):
    def __init__(self, user: discord.User, moderator: discord.Member):
        super().__init__(timeout=30)
        self.user = user
        self.moderator = moderator
    
    @discord.ui.button(label="Supprimer toutes les sanctions", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_all_sanctions(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user.id != self.moderator.id:
            return await interaction.response.send_message("❌ Vous n'êtes pas autorisé à faire cela.", ephemeral=True)
        
        user_sanctions = sanctions_db.get_user_sanctions(self.user.id)
        total = len(user_sanctions["tempmutes"]) + len(user_sanctions["timeouts"]) + len(user_sanctions["bans"]) + len(user_sanctions["warns"])
        
        sanctions_db.delete_user_sanctions(self.user.id)
        
        embed = discord.Embed(
            color=discord.Color.from_str("#FFFFFF"),
            timestamp=datetime.now()
        )
        embed.set_thumbnail(url=self.user.display_avatar.url)
        embed.description = f"✅ {total} sanction(s) supprimée(s) pour {self.user.mention}"
        
        await interaction.response.edit_message(embed=embed, view=None)

# Configuration du bot
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="/", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ {bot.user} est connecté !")
    print(f"👥 Sur {len(bot.guilds)} serveur(s)")
    print(f"🆔 ID: {bot.user.id}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="/help pour l'aide"))

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_expired_sanctions.start()
    
    def cog_unload(self):
        self.check_expired_sanctions.cancel()
    
    @commands.slash_command(name="tempmute", description="Tempmute un utilisateur")
    async def tempmute(
        self,
        ctx,
        user: Option(discord.Member, "Utilisateur à tempmute", required=True),
        duration: Option(str, "Durée", choices=list(TEMPMUTE_DURATIONS.keys()), required=True),
        reason: Option(str, "Raison", choices=PREDEFINED_REASONS["tempmute"], required=True)
    ):
        if not ctx.author.guild_permissions.moderate_members:
            return await ctx.respond("❌ Permission refusée.", ephemeral=True)
        
        duration_seconds = TEMPMUTE_DURATIONS[duration]
        
        # Créer ou récupérer le rôle Muted
        mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if not mute_role:
            try:
                mute_role = await ctx.guild.create_role(
                    name="Muted",
                    permissions=discord.Permissions(send_messages=False, speak=False, add_reactions=False),
                    color=discord.Color.dark_gray()
                )
                
                # Appliquer les permissions
                for channel in ctx.guild.channels:
                    if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                        try:
                            await channel.set_permissions(
                                mute_role,
                                send_messages=False,
                                speak=False,
                                add_reactions=False
                            )
                        except:
                            continue
            except:
                return await ctx.respond("❌ Impossible de créer le rôle Muted.", ephemeral=True)
        
        try:
            await user.add_roles(mute_role, reason=f"Tempmute: {reason} | Par: {ctx.author}")
            
            # Enregistrer la sanction
            sanction = Sanction(user.id, ctx.author.id, reason, "tempmute", duration_seconds)
            sanctions_db.add_sanction(sanction)
            
            # Embed
            embed = discord.Embed(
                color=discord.Color.from_str("#FFFFFF"),
                timestamp=datetime.now()
            )
            embed.description = f"{user.mention} a été tempmute pendant {duration} pour {reason}"
            
            await ctx.respond(embed=embed)
            
        except discord.Forbidden:
            await ctx.respond("❌ Permission refusée pour mute cet utilisateur.", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"❌ Erreur: {str(e)}", ephemeral=True)
    
    @commands.slash_command(name="unmute", description="Retire le mute d'un utilisateur")
    async def unmute(
        self,
        ctx,
        user: Option(discord.Member, "Utilisateur à unmute", required=True),
        reason: Option(str, "Raison (facultative)", required=False, default="Aucune raison spécifiée")
    ):
        if not ctx.author.guild_permissions.moderate_members:
            return await ctx.respond("❌ Permission refusée.", ephemeral=True)
        
        mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if not mute_role or mute_role not in user.roles:
            return await ctx.respond(f"❌ {user.mention} n'est pas mute.", ephemeral=True)
        
        try:
            await user.remove_roles(mute_role, reason=f"Unmute: {reason} | Par: {ctx.author}")
            
            # Embed
            embed = discord.Embed(
                color=discord.Color.from_str("#FFFFFF"),
                timestamp=datetime.now()
            )
            embed.description = f"{user.mention} a été unmute"
            if reason != "Aucune raison spécifiée":
                embed.description += f" pour {reason}"
            
            await ctx.respond(embed=embed)
            
        except discord.Forbidden:
            await ctx.respond("❌ Permission refusée pour unmute cet utilisateur.", ephemeral=True)
    
    @commands.slash_command(name="timeout", description="Timeout un utilisateur")
    async def timeout(
        self,
        ctx,
        user: Option(discord.Member, "Utilisateur à timeout", required=True),
        duration: Option(str, "Durée", choices=list(TIMEOUT_DURATIONS.keys()), required=True),
        reason: Option(str, "Raison", choices=PREDEFINED_REASONS["timeout"], required=True)
    ):
        if not ctx.author.guild_permissions.moderate_members:
            return await ctx.respond("❌ Permission refusée.", ephemeral=True)
        
        duration_seconds = TIMEOUT_DURATIONS[duration]
        expire_time = datetime.now() + timedelta(seconds=duration_seconds)
        
        try:
            await user.timeout(expire_time, reason=f"Timeout: {reason} | Par: {ctx.author}")
            
            # Enregistrer la sanction
            sanction = Sanction(user.id, ctx.author.id, reason, "timeout", duration_seconds)
            sanctions_db.add_sanction(sanction)
            
            # Embed
            embed = discord.Embed(
                color=discord.Color.from_str("#FFFFFF"),
                timestamp=datetime.now()
            )
            embed.description = f"{user.mention} a été timeout pour {reason} pendant {duration}"
            
            await ctx.respond(embed=embed)
            
        except discord.Forbidden:
            await ctx.respond("❌ Permission refusée pour timeout cet utilisateur.", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"❌ Erreur: {str(e)}", ephemeral=True)
    
    @commands.slash_command(name="untimeout", description="Retire le timeout d'un utilisateur")
    async def untimeout(
        self,
        ctx,
        user: Option(discord.Member, "Utilisateur à untimeout", required=True),
        reason: Option(str, "Raison (facultative)", required=False, default="Aucune raison spécifiée")
    ):
        if not ctx.author.guild_permissions.moderate_members:
            return await ctx.respond("❌ Permission refusée.", ephemeral=True)
        
        if user.timed_out_until is None:
            return await ctx.respond(f"❌ {user.mention} n'est pas timeout.", ephemeral=True)
        
        try:
            await user.timeout(None, reason=f"Untimeout: {reason} | Par: {ctx.author}")
            
            # Embed
            embed = discord.Embed(
                color=discord.Color.from_str("#FFFFFF"),
                timestamp=datetime.now()
            )
            embed.description = f"{user.mention} n'est plus timeout"
            if reason != "Aucune raison spécifiée":
                embed.description += f" pour {reason}"
            
            await ctx.respond(embed=embed)
            
        except discord.Forbidden:
            await ctx.respond("❌ Permission refusée pour untimeout cet utilisateur.", ephemeral=True)
    
    @commands.slash_command(name="ban", description="Bannir un utilisateur")
    async def ban(
        self,
        ctx,
        user: Option(discord.Member, "Utilisateur à bannir", required=True),
        reason: Option(str, "Raison", required=True)
    ):
        if not ctx.author.guild_permissions.ban_members:
            return await ctx.respond("❌ Permission refusée.", ephemeral=True)
        
        try:
            await user.ban(reason=f"Ban: {reason} | Par: {ctx.author}", delete_message_days=0)
            
            # Enregistrer la sanction
            sanction = Sanction(user.id, ctx.author.id, reason, "ban")
            sanctions_db.add_sanction(sanction)
            
            # Embed
            embed = discord.Embed(
                color=discord.Color.from_str("#FFFFFF"),
                timestamp=datetime.now()
            )
            embed.description = f"{user.mention} a été banni pour {reason}"
            
            await ctx.respond(embed=embed)
            
        except discord.Forbidden:
            await ctx.respond("❌ Permission refusée pour bannir cet utilisateur.", ephemeral=True)
    
    @commands.slash_command(name="unban", description="Débannir un utilisateur")
    async def unban(
        self,
        ctx,
        user_id: Option(str, "ID de l'utilisateur à débannir", required=True)
    ):
        if not ctx.author.guild_permissions.ban_members:
            return await ctx.respond("❌ Permission refusée.", ephemeral=True)
        
        try:
            user_id_int = int(user_id)
            user = await self.bot.fetch_user(user_id_int)
            await ctx.guild.unban(user, reason=f"Unban par {ctx.author}")
            
            # Embed
            embed = discord.Embed(
                color=discord.Color.from_str("#FFFFFF"),
                timestamp=datetime.now()
            )
            embed.description = f"{user.mention} a été débanni"
            
            await ctx.respond(embed=embed)
            
        except ValueError:
            await ctx.respond("❌ ID invalide.", ephemeral=True)
        except discord.NotFound:
            await ctx.respond("❌ Utilisateur non trouvé ou non banni.", ephemeral=True)
        except discord.Forbidden:
            await ctx.respond("❌ Permission refusée pour débannir.", ephemeral=True)
    
    @commands.slash_command(name="warn", description="Avertir un utilisateur")
    async def warn(
        self,
        ctx,
        user: Option(discord.Member, "Utilisateur à avertir", required=True),
        reason: Option(str, "Raison", required=True)
    ):
        if not ctx.author.guild_permissions.moderate_members:
            return await ctx.respond("❌ Permission refusée.", ephemeral=True)
        
        # Enregistrer le warn
        sanction = Sanction(user.id, ctx.author.id, reason, "warn")
        sanctions_db.add_sanction(sanction)
        
        # Embed
        embed = discord.Embed(
            color=discord.Color.from_str("#FFFFFF"),
            timestamp=datetime.now()
        )
        embed.description = f"{user.mention} a été warn pour {reason}"
        
        await ctx.respond(embed=embed)
    
    @commands.slash_command(name="sanctions", description="Voir les sanctions d'un utilisateur")
    async def sanctions(
        self,
        ctx,
        user: Option(discord.User, "Utilisateur", required=True)
    ):
        if not ctx.author.guild_permissions.moderate_members:
            return await ctx.respond("❌ Permission refusée.", ephemeral=True)
        
        user_sanctions = sanctions_db.get_user_sanctions(user.id)
        
        if not any(user_sanctions.values()):
            return await ctx.respond(f"ℹ️ {user.mention} n'a aucune sanction enregistrée.", ephemeral=True)
        
        view = SanctionsView(user, user_sanctions["tempmutes"], user_sanctions["timeouts"], 
                           user_sanctions["bans"], ctx.author)
        embed = await view.create_embed()
        
        await ctx.respond(embed=embed, view=view)
    
    @commands.slash_command(name="delsanction", description="Supprimer les sanctions d'un utilisateur")
    async def delsanction(
        self,
        ctx,
        user: Option(discord.User, "Utilisateur", required=True)
    ):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.respond("❌ Permission refusée.", ephemeral=True)
        
        user_sanctions = sanctions_db.get_user_sanctions(user.id)
        total = len(user_sanctions["tempmutes"]) + len(user_sanctions["timeouts"]) + \
                len(user_sanctions["bans"]) + len(user_sanctions["warns"])
        
        embed = discord.Embed(
            color=discord.Color.from_str("#FFFFFF"),
            timestamp=datetime.now()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.description = f"Supprimer les sanctions de {user.mention} ?\nTotal: {total} sanction(s)"
        
        view = DeleteSanctionsView(user, ctx.author)
        await ctx.respond(embed=embed, view=view, ephemeral=True)
    
    @commands.slash_command(name="help", description="Affiche l'aide des commandes")
    async def help_command(self, ctx):
        embed = discord.Embed(
            title="📚 Commandes de Modération",
            color=discord.Color.blue(),
            description="Voici toutes les commandes disponibles :"
        )
        
        embed.add_field(
            name="🔇 **/tempmute**",
            value="`user` `duration` `reason`\nMute temporaire un utilisateur",
            inline=False
        )
        embed.add_field(
            name="🔊 **/unmute**",
            value="`user` `[reason]`\nRetire le mute d'un utilisateur",
            inline=False
        )
        embed.add_field(
            name="⏰ **/timeout**",
            value="`user` `duration` `reason`\nMet un utilisateur en timeout",
            inline=False
        )
        embed.add_field(
            name="✅ **/untimeout**",
            value="`user` `[reason]`\nRetire le timeout d'un utilisateur",
            inline=False
        )
        embed.add_field(
            name="🔨 **/ban**",
            value="`user` `reason`\nBannit un utilisateur",
            inline=False
        )
        embed.add_field(
            name="🔄 **/unban**",
            value="`user_id`\nDébannit un utilisateur",
            inline=False
        )
        embed.add_field(
            name="⚠️ **/warn**",
            value="`user` `reason`\nDonne un avertissement",
            inline=False
        )
        embed.add_field(
            name="📋 **/sanctions**",
            value="`user`\nAffiche les sanctions d'un utilisateur",
            inline=False
        )
        embed.add_field(
            name="🗑️ **/delsanction**",
            value="`user`\nSupprime toutes les sanctions d'un utilisateur",
            inline=False
        )
        
        embed.set_footer(text="Toutes les commandes utilisent des embeds blancs")
        await ctx.respond(embed=embed, ephemeral=True)
    
    @tasks.loop(seconds=30)
    async def check_expired_sanctions(self):
        """Vérifie les sanctions expirées"""
        now = datetime.now()
        
        # Vérifier les tempmutes expirés
        for sanction in sanctions_db.tempmutes:
            if not sanction.expired and sanction.duration:
                expire_time = sanction.date + timedelta(seconds=sanction.duration)
                if now >= expire_time:
                    # Retirer le rôle Muted
                    for guild in self.bot.guilds:
                        try:
                            member = await guild.fetch_member(sanction.user_id)
                            mute_role = discord.utils.get(guild.roles, name="Muted")
                            if mute_role and mute_role in member.roles:
                                await member.remove_roles(mute_role, reason="Tempmute expiré")
                        except:
                            continue
                    sanction.expired = True
        
        # Vérifier les timeouts expirés
        for sanction in sanctions_db.timeouts:
            if not sanction.expired and sanction.duration:
                expire_time = sanction.date + timedelta(seconds=sanction.duration)
                if now >= expire_time:
                    sanction.expired = True

# Ajouter le cog au bot
async def setup(bot):
    await bot.add_cog(Moderation(bot))

# Lancer le bot
@bot.event
async def on_ready():
    print(f"✅ {bot.user} est connecté !")
    await bot.add_cog(Moderation(bot))

# Configuration pour Railway
if __name__ == "__main__":
    print("🚀 Démarrage du bot sur Railway...")
    print(f"🔑 Token récupéré: {'OUI' if TOKEN else 'NON'}")
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Erreur lors du démarrage: {e}")