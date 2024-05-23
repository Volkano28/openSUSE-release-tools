#!/usr/bin/python3

# TODO: solve all devel packages to include

import cmdln
import os
import re

import ToolBase
import logging

from osc import conf
from osclib.conf import Config
from osclib.stagingapi import StagingAPI
from pkglistgen.engine import Engine, ENGINE_NAMES
from pkglistgen.tool import PkgListGen, MismatchedRepoException
from pkglistgen.update_repo_handler import update_project


class CommandLineInterface(ToolBase.CommandLineInterface):
    SCOPES = ['target', 'ring1']

    def __init__(self, *args, **kwargs):
        ToolBase.CommandLineInterface.__init__(self, args, kwargs)

    def setup_tool(self):
        tool = PkgListGen()
        if self.options.debug:
            logging.basicConfig(level=logging.DEBUG)
        elif self.options.verbose:
            logging.basicConfig(level=logging.INFO)

        return tool

    @cmdln.option('--fixate', help='Set category to fixed and merge remaining files')
    def do_handle_update_repos(self, subcmd, opts, project):
        """${cmd_name}: Update 00update-repos

        Reads config.yml from 00update-repos and will create required solv files

        ${cmd_usage}
        ${cmd_option_list}
        """
        return update_project(conf.config['apiurl'], project, opts.fixate)

    @cmdln.option('-f', '--force', action='store_true', help='continue even if build is in progress')
    @cmdln.option('-d', '--dry', help='no modifications uploaded')
    @cmdln.option('-p', '--project', help='target project')
    @cmdln.option('-g', '--git-url', help='git repository for target project')
    @cmdln.option('-s', '--scope', help=f"scope on which to operate ({', '.join(SCOPES)}, staging:$letter)")
    @cmdln.option('--engine', help=f"engine to be used. Available engines are: {', '.join(ENGINE_NAMES)}", default=Engine.legacy.name)
    @cmdln.option('--no-checkout', action='store_true', help='reuse checkout in cache')
    @cmdln.option('--stop-after-solve', action='store_true', help='only create group files')
    @cmdln.option('--staging', help='Only solve that one staging')
    @cmdln.option('--only-release-packages', action='store_true', help='Generate 000release-packages only')
    @cmdln.option('--custom-cache-tag', help='add custom tag to cache dir to avoid issues when running in parallel')
    def do_update_and_solve(self, subcmd, opts):
        """${cmd_name}: update and solve for given scope

        ${cmd_usage}
        ${cmd_option_list}
        """

        if opts.staging:
            match = re.match('(.*):Staging:(.*)', opts.staging)
            opts.scope = 'staging:' + match.group(2)
            if opts.project:
                raise ValueError('--staging and --project conflict')
            opts.project = match.group(1)
        elif not opts.project:
            raise ValueError('project is required')

        if not opts.scope:
            raise ValueError('--scope or --staging required')

        if opts.engine not in ENGINE_NAMES:
            raise ValueError(f"Illegal engine: {opts.engine} . Supported engines are {', '.join(ENGINE_NAMES)}.")
        elif opts.engine == Engine.product_composer.name and opts.only_release_packages:
            raise ValueError(f"--only-release-packages makes no sense with {Engine.product_composer.name} engine, as it does not handle "
                             "000release-packages!")

        apiurl = conf.config['apiurl']
        Config(apiurl, opts.project)
        target_config = conf.config[opts.project]

        # Store target project as opts.project will contain subprojects.
        target_project = opts.project

        api = StagingAPI(apiurl, target_project)

        main_repo = target_config['main-repo']

        # used by product converter
        # these needs to be kept in sync with OBS config
        if apiurl.find('suse.de') > 0:
            os.environ['OBS_NAME'] = 'build.suse.de'
        if apiurl.find('opensuse.org') > 0:
            os.environ['OBS_NAME'] = 'build.opensuse.org'

        def solve_project(project, scope: str):
            try:
                self.tool.reset()
                self.tool.dry_run = self.options.dry
                return self.tool.update_and_solve_target(api, target_project, target_config, main_repo,
                                                         git_url=opts.git_url, project=project, scope=scope,
                                                         engine=Engine[opts.engine],
                                                         force=opts.force, no_checkout=opts.no_checkout,
                                                         only_release_packages=opts.only_release_packages,
                                                         stop_after_solve=opts.stop_after_solve,
                                                         custom_cache_tag=opts.custom_cache_tag)
            except MismatchedRepoException:
                logging.error("Failed to create weakremovers.inc due to mismatch in repos - project most likey started building again!")
                # for stagings we have to be strict on the exit value
                if scope == 'staging':
                    return 1
                return 0

        scope = opts.scope
        if scope.startswith('staging:'):
            letter = re.match('staging:(.*)', scope).group(1)
            return solve_project(api.prj_from_short(letter), 'staging')
        elif scope == 'target':
            return solve_project(target_project, scope)
        elif scope == 'ring1':
            return solve_project(api.rings[1], scope)
        else:
            raise ValueError(f"scope \"{scope}\" must be one of: {', '.join(self.SCOPES)}")
