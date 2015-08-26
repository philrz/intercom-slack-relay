#!/usr/bin/env python

import sys
import json
import copy
import requests
import datetime
import time
import argparse
import logging
import smtplib
import traceback
import socket
import string
from email.mime.text import MIMEText
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup

# Intercom unfortunately is not willing to provide a whitelist of source IP addresses from which
# we might get webhook notifications. As a result, the TCP port has to be open to the world.
# Furthermore, since the Flask web server is single-threaded, it's prone to blocking, such as
# if some attacker did a "telnet <server> <port>" and just let it sit there, that would ordinarily
# cause all subsequent incoming connections to hang waiting for us to finish processing the first
# one. By setting the TCP socket timeout to 10 seconds, this means we'll close all such connections
# if they've not sent us a byte in that amount of time, after which we'll unblock and handle the
# other legit incoming notifications.
socket.setdefaulttimeout(10)

app = Flask(__name__)

def prep_logging(name, log_filepath):
    """Set up logging to go to the console and a file simultaneously."""
    newlogger = logging.getLogger(name)
    newlogger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    filehandler = logging.FileHandler(log_filepath)
    consolehandler = logging.StreamHandler()
    for handler in [filehandler, consolehandler]:
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        newlogger.addHandler(handler)
    return newlogger

def parse_args():
    """Get command-line arguments."""
    parser = argparse.ArgumentParser(description='Start an Intercom/Slack relay agent')
    parser.add_argument('--port', help='TCP port to listen on for Intercom notifications',
                        dest='port', required=True)
    parser.add_argument('--appid', help='Intercom App ID', dest='appid', required=True)
    parser.add_argument('--apikey', help='Intercom API Key', dest='apikey', required=True)
    parser.add_argument('--token', help='Slack API token', dest='token', required=True)
    parser.add_argument('--channel', help='Slack channel to send messages to (no hash)',
                        dest='channel', required=True)
    parser.add_argument('--backupchannel', help='Backup channel with native relay pointing at it (no hash)',
                        dest='backupchannel', required=True)
    parser.add_argument('--email', help='E-mail addrress of who to contact on failures',
                        dest='email', required=True)
    return parser.parse_args()

def failmail(addr, message, copy_to_slack=True):
    msg = MIMEText(message)
    msg['Subject'] = 'intslack failure'
    msg['From'] = addr
    msg['To'] = addr
    logger.info('Sending Failmail:\n' + msg.as_string())
    s = smtplib.SMTP('localhost')
    s.sendmail(addr, [addr], msg.as_string())
    s.quit()

    if copy_to_slack:
        slack_message = {}
        slack_message['text'] = "!!! Error relaying message from Intercom to Slack. <mailto:" + email + "|" + email + "> will look into it. \nCheck #" + backupchannel + " for missed message.\n" + message
        slack_message['color'] = "danger"
        slacksend_channel(slack_message, slackchannel)

def user_info(id):
    try:
        info = {}
        req = session.get("https://api.intercom.io/users/" + id, auth=(appid, apikey), headers=headers)
        if req.status_code == 200:
            u = req.json()
            logger.info('User record from Infocom:\n' + json.dumps(u, sort_keys=True, indent=4))
        else:
            failmail(email, 'Unexpected status code ' + str(req.status_code) +
                     ' when getting user info from Intercom')
            return None

        if u['name']:
            known_as = u['name']
        else:
            known_as = u['email']
        info['name'] = ("<https://app.intercom.io/a/apps/" + appid + "/users/" + u['id'] + "|" + known_as + ">")
        companies = ''
        for company in u['companies']['companies']:
            # There's some Company records in Intercom that have an id but no name.
            if 'name' in company:
                companies = companies + company['name'] + ' '
        if companies == '':
            info['company'] = 'no company'
        else:
            info['company'] = ("<https://app.intercom.io/a/apps/" + appid + "/companies/" +
                               company['id'] + "|" + companies[:-1] + ">")
        return info
    except:
        failmail(email, 'Failure on processing Intercom user info:\n' + traceback.format_exc())
        return None

def clean_up(body):
    body = body.replace('<br>', '\n')
    body = body.replace('</p><p>', '\n')
    body = body.replace('<p>', '')
    soup = BeautifulSoup(body)
    return soup.get_text()

def intercom_parse(notification):

    try:
        if notification['topic'] == 'conversation.admin.replied':
            for part in notification['data']['item']['conversation_parts']['conversation_parts']:
                part['body'] = clean_up(part['body'])
                uinfo = user_info(notification['data']['item']['user']['id'])
                if uinfo:
                    message = (part['author']['name'] + " replied to <" +
                    notification['data']['item']['links']['conversation_web'] + "|a conversation> with " +
                        uinfo['name'] + " (" +
                        uinfo['company'] + ")\n" +
                        part['body'])
                    return({"text": message, "color": "ffce49"})
                else:
                    return None
    
        elif notification['topic'] == 'conversation.user.replied':
            for part in notification['data']['item']['conversation_parts']['conversation_parts']:
                part['body'] = clean_up(part['body'])
                uinfo = user_info(part['author']['id'])
                if uinfo:
                    message = (uinfo['name'] + " (" +
                        uinfo['company'] + ") replied to <" + 
                        notification['data']['item']['links']['conversation_web'] + "|a conversation> with " +
                        notification['data']['item']['assignee']['name'] + '\n' +
                        part['body'])
                    return({"text": message, "color": "1414ff"})
                else:
                    return None

        elif notification['topic'] in [ 'conversation.admin.opened', 'conversation.admin.closed' ]:
            operation = string.split(notification['topic'], '.')[2]
            for part in notification['data']['item']['conversation_parts']['conversation_parts']:
                part['body'] = clean_up(part['body'])
                uinfo = user_info(notification['data']['item']['user']['id'])
                if uinfo:
                    message = (part['author']['name'] + " " + operation + " <" +
                    notification['data']['item']['links']['conversation_web'] + "|a conversation> with " +
                        uinfo['name'] + " (" +
                        uinfo['company'] + ")\n" +
                        part['body'])
                    return({"text": message, "color": "ffce49"})
                else:
                    return None

        elif notification['topic'] == 'conversation.admin.closed':
            for part in notification['data']['item']['conversation_parts']['conversation_parts']:
                part['body'] = clean_up(part['body'])
                uinfo = user_info(notification['data']['item']['user']['id'])
                if uinfo:
                    message = (part['author']['name'] + " closed <" +
                    notification['data']['item']['links']['conversation_web'] + "|a conversation> with " +
                        uinfo['name'] + " (" +
                        uinfo['company'] + ")\n" +
                        part['body'])
                    return({"text": message, "color": "ffce49"})
                else:
                    return None

        elif notification['topic'] == 'conversation.admin.assigned':
            for part in notification['data']['item']['conversation_parts']['conversation_parts']:
                part['body'] = clean_up(part['body'])
                uinfo = user_info(notification['data']['item']['user']['id'])
                if uinfo:
                    message = (part['author']['name'] + " assigned <" +
                    notification['data']['item']['links']['conversation_web'] + "|a conversation> with " +
                        uinfo['name'] + " (" +
                        uinfo['company'] +
                        ") to " + part['assigned_to']['name'] + "\n" +
                        part['body'])
                    return({"text": message, "color": "ffce49"})
                else:
                    return None

        elif notification['topic'] == 'conversation.user.created':
            part = notification['data']['item']['conversation_message']
            part['body'] = clean_up(part['body'])
            uinfo = user_info(part['author']['id'])
            if uinfo:
                message = (uinfo['name'] + " (" +
                    uinfo['company'] + ") started a new <" +
                    notification['data']['item']['links']['conversation_web'] + "|conversation> with " +
                    notification['data']['item']['assignee']['name'] + '\n' +
                    part['body'])
                return({"text": message, "color": "1414ff"})
            else:
                return None

        elif notification['topic'] == 'conversation.admin.noted':
            for part in notification['data']['item']['conversation_parts']['conversation_parts']:
                part['body'] = clean_up(part['body'])
                uinfo = user_info(notification['data']['item']['user']['id'])
                if uinfo:
                    message = (part['author']['name'] + " added <" +
                        notification['data']['item']['links']['conversation_web'] + "|an internal note> to <" +
                        notification['data']['item']['links']['conversation_web'] + "|a conversation> with " +
                        uinfo['name'] + " (" +
                        uinfo['company'] + ")\n" +
                        part['body'])
                    return({"text": message, "color": "ffce49"})
                else:
                    return None

        else:
            failmail(email, 'Received an unsupported Intercom notification type:\n' + notification['topic'])
            return None

    except:
        failmail(email, 'Failure parsing Intercom notification:\n' + traceback.format_exc())
        return None

def slacksend_channel(message, channel_name):
    try:
        args = copy.deepcopy(slackauth)
        args['name'] = channel_name
        logger.info('Joining channel on Slack:\n' + json.dumps(args, sort_keys=True, indent=4))
        req = session.post("https://slack.com/api/channels.join", data=args)
        if req.status_code == 200:
            resp = req.json()
            logger.info('Response from Slack channel join:\n' + json.dumps(resp, sort_keys=True, indent=4))
            channel = req.json()
        else:
            failmail(email, 'Unexpected response code ' + str(req.status_code) + ' when joining Slack channel', copy_to_slack=False)
            return False
    
        args = copy.deepcopy(slackauth)
        args['channel'] = channel['channel']['id']
        args['username'] = 'Intercom'

        # If the message is too big, Slack will send us a response code 414. Keep chopping the message in
        # half until it goes through.
        msglen = len(message['text'])
        trailer = ''
        msgsent = False
        while not msgsent:
            att = [{ "fallback": message['text'][:msglen] + trailer,
                     "text": message['text'][:msglen] + trailer,
                     "color": message['color'] }]
            args['attachments'] = json.dumps(att)
            
            logger.info('Posting message to Slack:\n' + json.dumps(args, sort_keys=True, indent=4))
            req = session.post("https://slack.com/api/chat.postMessage", params=args)
            if req.status_code == 200:
                resp = req.json()
                logger.info('Response from Slack message post:\n' + json.dumps(resp, sort_keys=True, indent=4))
                return resp['ok']
            elif req.status_code == 414:
                logger.info('Response code 414 from Slack message post. Cutting in half and trying again.\n')
                trailer = '\n\n[This message was too long to relay to Slack. You\'ll have to click to Intercom to see the whole thing.]\n'
                msglen /= 2
                time.sleep(1)
            else:
                failmail(email, 'Unexpected response code ' + str(req.status_code) +
                         ' when posting message to Slack', copy_to_slack=False)
                return False

        # Always sleep an extra second, as the Slack API says it will cut us off if we send more frequently
        # than once per second.
        time.sleep(1)
            
    except:
        failmail(email, 'Failure posting message to Slack:\n' + traceback.format_exc(), copy_to_slack=False)
        return False

@app.route('/intercom', methods=['POST'])
def process_notification():
    try:
        notification = request.get_json(force=True)
        logger.info("Intercom notification received:\n" + json.dumps(notification, sort_keys=True, indent=4))
        message = intercom_parse(notification)
        if message:
           if slacksend_channel(message, slackchannel):
               logger.info('Successfully relayed a parsed Intercom message to Slack')
               return("OK")
           else:
               logger.info('Something went wrong when trying to send to Slack')
        else:
            logger.info('Was not able to parse the Intercom notification into a sendable message')

    except:
        failmail(email, 'General failure processing Intercom notification:\n' + traceback.format_exc())

cmdline_args = parse_args()
port = int(cmdline_args.port)
appid = cmdline_args.appid
apikey = cmdline_args.apikey
email = cmdline_args.email
slackauth = { 'token': cmdline_args.token }
slackchannel = cmdline_args.channel
backupchannel = cmdline_args.backupchannel
logger = prep_logging('intslack', 'intslack.log')
headers = { "Accept": "application/json" }
session = requests.Session()

if __name__ == '__main__':
    startup_msg = {
                      "text": "Custom <https://github.com/jut-io/intercom-slack-relay|intercom-slack-relay> starting up\nMaintained by <mailto:" + email + "|" + email + ">\nCheck #" + backupchannel + " for any messages that may have been missed while relay was offline",
                      "color": "danger"
                  }
    slacksend_channel(startup_msg, slackchannel)
    app.run(host='0.0.0.0', port=port)
