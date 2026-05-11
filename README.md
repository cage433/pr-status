Utility for keeping track of PR reviews
---------------------------------------

This is a repl utility, to produce pivot reports for github pull requests and their associated comments. 

Reports can be sorted and filtered; run the help command for a description and examples of the 
various columns and filters.

A key feature is the 'marking' of pull requests. This is a simple mapping of PR id to a timestamp, 
the effect of which is to ignore all comments _before_ that timestamp. The intended use case is
when having reviewed a pull request the user can mark it, subsequent reports can exclude any pull requests that have no new comments since the mark


Usage:
------
    
    ./pr-status.sh

this will create a config file in ~/.conf/pr-status/config, and an empty marks file in ~/.cache/pr-status/marks

the script launches a repl, from which reports can be run and marks set/unset

run 'help' from the repl for more details of usage and options

Config:
-------

see sample.config for a list of settings

Requirements:
-------------

'uv' and 'rlwrap'

the script will check for these on start up.

Walkthrough:
------------

[walkthrough.mov](src/pr_status/help/walkthrough-720p.mov)

Note that when the walkthtough was recorded, there was a bug that meant comments before the mark
weren't ignored. That has since been fixed.
