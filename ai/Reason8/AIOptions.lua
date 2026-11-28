-- Options of the Reason8 AI: the same keys BARb (CircuitAI) reads.
--
-- Two defaults differ from BARb's:
--   game_config = false  The scripts and configs next to the library are the
--                        only copy; the game archive has none for this AI.
--   profile     = hard   The only profile the variant is built with.
--
-- Three are Reason8's own, read by our BARb library:
--   command_budget       How the AI keeps to the action budget of ADR 0008.
--   builder_orders       Who decides the builders' orders during the opening:
--                        the opening table, or the model (ADR 0019).
--   skill                The player's skill the model is told (ADR 0019);
--                        empty: the 90th percentile of the players it was
--                        trained on.

local options = {
	{
		key = 'performance',
		name = 'Performance Relevant Settings',
		desc = 'These settings may be relevant for both CPU usage and AI difficulty.',
		type = 'section',
	},
	{
		key = 'cheating',
		name = 'LOS vision',
		desc = 'Enable global sight. Reason8 is meant to play without it.',
		type = 'bool',
		section = 'performance',
		def = false,
	},
	{
		key = 'comm_merge',
		name = 'Merge neighbour AIs',
		desc = 'Merge spatially close ally commanders of this AI',
		type = 'bool',
		section = 'performance',
		def = false,
	},
	{
		key = 'ally_base',
		name = 'Avoid building in allied bases',
		desc = 'Do not build units near allied factories',
		type = 'bool',
		section = 'performance',
		def = true,
	},
	{
		key = 'disabledunits',
		name = 'Disabled units',
		desc = 'Disable usage of specific units.\nSyntax: armwar+armpw+raveparty\nkey: disabledunits',
		type = 'string',
		def = '',
	},
	{
		key = 'game_config',
		name = 'Load game config',
		desc = 'Look for scripts and configs in the game archive first',
		type = 'bool',
		def = false,
	},
	{
		key = 'profile',
		name = 'Profile',
		desc = 'BARb profile the openings are layered on.\nkey: profile',
		type = 'list',
		def = 'hard',
		items = {
			{
				key = 'hard',
				name = 'Hard',
				desc = 'BARb hard, with Reason8 openings',
			},
		},
	},
	{
		key = 'command_budget',
		name = 'Command budget',
		desc = 'How the AI keeps to a strong player\'s action budget (skill 30-40).\nkey: command_budget',
		type = 'list',
		def = 'defer',
		items = {
			{
				key = 'defer',
				name = 'Defer',
				desc = 'Hold commands over the budget and send them later, in order',
			},
			{
				key = 'count',
				name = 'Count',
				desc = 'Only count and log the commands',
			},
			{
				key = 'off',
				name = 'Off',
				desc = 'No governor',
			},
		},
	},
	{
		key = 'reaction_delays',
		name = 'Reaction delays',
		desc = 'Whether an idle factory or builder waits as long as a player takes to notice it.\nkey: reaction_delays',
		type = 'list',
		def = 'on',
		items = {
			{
				key = 'on',
				name = 'On',
				desc = 'Idle units wait a delay measured from players (skill 30-40)',
			},
			{
				key = 'off',
				name = 'Off',
				desc = 'Idle units get their next order at once',
			},
		},
	},
	{
		key = 'builder_orders',
		name = 'Builder orders',
		desc = 'Who decides the builders\' orders during the opening.\nkey: builder_orders',
		type = 'list',
		def = 'opening',
		items = {
			{
				key = 'opening',
				name = 'Opening',
				desc = 'The commander and the first factory play an opening of the start position',
			},
			{
				key = 'model',
				name = 'Model',
				desc = 'The model decides the next order of every idle builder',
			},
		},
	},
	{
		key = 'skill',
		name = 'Skill',
		desc = 'The rating of the player the model plays as, when it decides builders\' orders; empty: the 90th percentile of its training players.\nkey: skill',
		type = 'string',
		def = '',
	},
}

return options
