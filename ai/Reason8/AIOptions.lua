-- Options of the Reason8 AI: the same keys BARb (CircuitAI) reads.
--
-- Two defaults differ from BARb's:
--   game_config = false  The scripts and configs next to the library are the
--                        only copy; the game archive has none for this AI.
--   profile     = hard   The only profile the variant is built with.

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
}

return options
