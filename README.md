intercom-slack-relay
====================
This is a custom relayer that receives notifications from [Intercom](https://www.intercom.io/) and relays them to a channel on [Slack](http://www.slack.com). It's intended to replace [the "stock" integration](http://docs.intercom.io/Integrations/slack-integration) because we found the messages it relayed to Slack were lacking. Specific examples of shortcomings:

* Messages were cut too short.
* Company name not visible.
* Simple formatting (such as newlines) were removed.

This meant we too often had to click on the link to see the full messages in the Intercom site, which slowed people down too much. People have been happier having more of the info up-front in the Slack message.

Configuration
-------------
Enable your notification stream from Intercom via <b>Integrations for ...</b> (which can be found under the gear icon in the upper-right corner of the window when logged into Intercom) then selecting <b>Webhooks</b> from the menu on the left. Enter a URL of the format `http://<hostname>:<port>/intercom` pointing at the host where you'll run the relayer. I've established with Intercom that they can't provide a specific set of source IP addresses from which their webhook might reach out, so this port would unfortunately need to be opened to the world.

It's recommended that you maintain the "stock" integration still relaying to a backup channel. This way you won't miss messages on errors, such as sudden changes in the notification format that the tool doesn't yet recognize. On the Intercom site, you can set/see the configuration for your backup "stock" integration by clicking <b>Slack</b> from the menu on the left.

Usage
-----
intslack is invoked as follows:

        ./intslack.py --port tcpport --appid intercom-app-id --apikey intercom-api-key --token slacktoken --email 'youremail@yourcompany.com' --channel 'customer-conversation' --backupchannel 'customer-conv-backup'

Options:

`port` - The TCP port on which the relayer will listen for incoming notifications from Intercom<br>
`appid` - Intercom App ID as found in "API Keys" screen on Intercom<br>
`appkey` - Intercom API Key as found in "API Keys" screen on Intercom<br>
`token` - Slack bearer token as found at https://api.slack.com/web<br>
`email` - Address of whoever should receive info about fatal errors<br>
`channel` - Slack channel name (without leading #) to which relayed messages should be sent<br>
`backupchannel` - Slack channel name (without leading #) to which people should be pointed when the relay fails<br>

Future enhancements
-------------------
This started as a Hack Day project at Jut and has already had many more enhancements than originally intended. Its current state is considered "good enough" for production use, especially because the "stock" relayer remains in service with its messages going to the <b>#customer-conv-backup</b> channel. However, in the event there should be demand in the future for more functionality, and someone has cycles to implement, here's a list of ideas.

1. Use HTTPS instead of HTTP, and have an actual username/password in the webhook. 

1. Add a "ping"-style endpoint so Nagios or other monitoring tools could confirm it's running ok and hence let us know if it isn't.

1. DRY out some of the code. There's a bit of redundant stuff in the processing of each Intercom notification type.

1. Locally cache information such as the Slack channel already having been joined or user data pulled down from Intercom. Right now we hit the APIs every time. Considering the low traffic and the APIs being lenient, this is not hurting us at the moment, but it would be friendlier and more efficient to cache.

1. Since intercom doesn't notify on the first message in a new conversation, backfill the first message to Slack when it recognizes the first customer reply.
