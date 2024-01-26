"""Enhances Amazon Lex Intent Recognition using LLMs"""
from datetime import datetime
import logging
import os

import boto3
from langchain.prompts import PromptTemplate
from langchain.llms.bedrock import Bedrock
from langchain.output_parsers import PydanticOutputParser
from langchain.pydantic_v1 import BaseModel, Field

logger = logging.getLogger()
logger.setLevel(logging.getLevelName(os.environ.get("LOGGING_LEVEL", "DEBUG")))

AWS_REGION = os.environ.get("REGION_NAME", None)
if AWS_REGION is None:
    raise Exception("REGION_NAME environment variable not set")

# The solution has been tested with Claude Instant or Claude v2
FOUNDATION_MODEL_ID = os.environ.get("MODEL_ID", "anthropic.claude-instant-v1")

CACHE_LIFETIME_SECONDS = int(os.environ.get("CACHE_LIFETIME_SECONDS", 300))
PREDICTION_CONFIDENCE = float(os.environ.get("PREDICTION_CONFIDENCE", 0.75))

class IntentOutput(BaseModel):
    '''Pydantic output parser'''
    intent_id: str = Field(description="The intent name.")
    confidence: float = Field(description="The confidence score for the intent.")

class LexBot:
    """
    Retrieves Amazon Lex bot intents and utterances configuration with caching functionality
    """
    
    client = None
    bot_info = {}
    intents_utterances = {}
    intent_names_ids = {}
    
    def __init__(self, client, event):
        self.client = client
        self.bot_info = {
            "bot_id": event['bot']['id'],
            "bot_version": event['bot']['version'],
            "locale_id": event['bot']['localeId'],
            "key": event['bot']['id'] 
                    + "_" \
                    + event['bot']['version'] \
                    + "_" \
                    + event['bot']['localeId']
        }

        self.intents_utterances = self.get_intents_utterances_from_cache(self.bot_info)
        
        # Creates a intent name to id mapping for convenience
        for intent_id in self.intents_utterances:
            self.intent_names_ids[self.intents_utterances[intent_id]['intent_name']] = intent_id

    def get_intents_utterances_from_cache(self, bot_info):
        '''
        Checks global cache for this bot, if exists, return intents and utterances from cache
        Otherwise, retrieve intents and utterances and caches it.
        Returns intents and utterances as a dictionary
        '''

        # Cache Miss
        if bot_info['key'] not in bot_cache:
            bot_intents_utterances = self.get_intents_utterances()
            bot_cache[bot_info['key']]={"content":bot_intents_utterances,
                                                 "timestamp": datetime.now()}
        # Cache Expired
        elif bot_info['key'] in bot_cache \
                and (datetime.now() \
                     - bot_cache[bot_info['key']]['timestamp']).total_seconds() > CACHE_LIFETIME_SECONDS:
            bot_intents_utterances = self.get_intents_utterances()
            bot_cache[bot_info['key']]={"content":bot_intents_utterances,
                                                 "timestamp": datetime.now()}
        # Cache Hit
        else:
            bot_intents_utterances = bot_cache[bot_info['key']]['content']

        return bot_intents_utterances

    def get_intents_utterances(self):
        '''
        Gets the intents and utterances for the bot
        '''
        #Retrieve intents for bot
        response = self.client.list_intents(
            botId=self.bot_info['bot_id'],
            botVersion=self.bot_info['bot_version'],
            localeId=self.bot_info['locale_id']
        )

        intents_utterances = {}
        for summary in response['intentSummaries']:

            # Handle if description is not in summary            
            if 'description' in summary:
                description = summary['description']
            else:
                description = ''
            
            intents_utterances[summary['intentId']] = {
                "intent_name": summary['intentName'],
                "description": description,
                "utterances": self.get_utterances(summary['intentId']),
        "parentIntentSignature": summary['parentIntentSignature'] if 'parentIntentSignature' in summary else ''
            }

        return intents_utterances

    def get_utterances(self, intent_id):
        '''Retrieves the utterances for an intent'''
        response = self.client.describe_intent(
            intentId=intent_id,
            botId=self.bot_info['bot_id'],
            botVersion=self.bot_info['bot_version'],
            localeId=self.bot_info['locale_id']
        )

        if 'sampleUtterances' in response:
            utterances = [x['utterance'] for x in response['sampleUtterances']]
            return utterances

        return []

    def delegate(self, intent):
        """Returns control back to Amazon Lex with the predicted intent"""
        return {
                    "sessionState": {
                        "dialogAction": {
                        "type": "Delegate"
                        },
                        "intent": {
                        "name": intent,
                        "state": "InProgress",
                        }
                    }
        }
     
    def close_fallback(self, intent):
        """Closes FallbackIntent when unable to recognize intent"""
    
        return {
                    "sessionState": {
                        "dialogAction": {
                        "type": "Close"
                        },
                        "intent": {
                        "name": intent,
                        "state": "Fulfilled",
                        }
                    }
        }

class LLMLexPrompt:
    '''
    Creates the prompt for the LLM
    '''
    
    prompt_formatted = ""
    
    def __init__(self, event, lex_bot: LexBot):
        self.prompt_template = """
            Human: You are a call center agent. You try to understand the intent given an utterance from the caller.
                        
            The available intents are as follows, the intent of the caller is highly likely to be one of these.
            <intents>
            {intents_block}
            </intents>
            
            The output format is:
            
            <thinking>
            </thinking>
            
            <output>
            {{
                "intent_id": intent_id,
                "confidence": confidence
            }}</output><STOP>
            
            For the given utterance, you try to categorize the intent of the caller to be one of the intents in <intents></intents> tags.
            If it does not match any intents or the utterance is blank, respond with FALLBCKINT and confidence of 1.00.
            Respond with the intent name and confidence between 0.00 and 1.00.
            
            Put your thinking in <thinking></thinking> tags before deciding on the intent.

            Utterance: {input}


            Assistant:
        """
        self.prompt = PromptTemplate.from_template(self.prompt_template)
        self.prompt_formatted = self.create_formatted_prompt(event, lex_bot)

    def create_intents_block(self, event, lex_bot: LexBot):
        '''
        Builds the {intents} block for the prompt template
        '''

        intent_ids_to_format = []

        #Add the intent id that has a parent intent of AMAZON.FallbackIntent
        for intent_id in lex_bot.intents_utterances:
            if lex_bot.intents_utterances[intent_id]['parentIntentSignature'] == 'AMAZON.FallbackIntent':
                intent_ids_to_format.append(intent_id)
                

        # Check if using Amazon Connect 'Get Customer Input' 'available_intents' session attribute
        if 'available_intents' in event['sessionState']['sessionAttributes']:
            if event['sessionState']['sessionAttributes']['available_intents'] != "":
                logger.info("Received session attributes from Amazon Connect")
                available_intents = \
                    event['sessionState']['sessionAttributes']['available_intents'].split(',')
                logger.info("Amazon Connect 'Get Customer Input' Intents: %s", available_intents)
                
                logger.info("Building intents to format")
                for intent in available_intents:
                    if intent in lex_bot.intent_names_ids:
                        #Appends the intent id
                        intent_ids_to_format.append(lex_bot.intent_names_ids[intent])
                    else:
                        logger.warning("WARNING: %s does not match configured Lex intents. \
                                    This intent will not be added.", intent)
            else:
                logger.warning("WARNING: available_intents is empty. Using all intents.")
                intent_ids_to_format = lex_bot.intents_utterances.keys()
        else:
            logger.warning("WARNING: available_intents is not found. Using all intents.")
            intent_ids_to_format = lex_bot.intents_utterances.keys()
        
        logger.debug("Intent ids to format: %s", intent_ids_to_format)
        
        # Build the intents block
        intents_block = ""

        # Append each intent to the intent_block
        for intent_id in intent_ids_to_format:
                
            # If there's no description, set it to empty
            if lex_bot.intents_utterances[intent_id]['description'] == 'nan':
                description = ''
            else:
                description = lex_bot.intents_utterances[intent_id]['description']
            
            # List of utterances to newline separated utterances
            if len(lex_bot.intents_utterances[intent_id]['utterances']) > 0:
                utterances = '\n'.join(lex_bot.intents_utterances[intent_id]['utterances'])
            else:
                utterances = ''
            
            intent = f"""
            <intent>
            <intent_id>{intent_id}<intent_id>
            <description>{description}</description>
            <utterance_examples>{utterances}</utterances_examples>
            </intent>
            """
            
            intents_block = intents_block + intent + "\n"

        logger.info ("Intents: %s", intents_block)

        return intents_block

    def create_formatted_prompt(self, event, lex_bot: LexBot):
        """Creates the formatted prompt"""
        logger.debug("Building prompt")
        prompt_template = PromptTemplate.from_template(self.prompt_template)
        prompt_template_formatted = prompt_template.format(
                                        intents_block=self.create_intents_block(event, lex_bot),
                                        input=event['inputTranscript'])
        logger.debug("Formatted Prompt: %s", prompt_template_formatted)
        return prompt_template_formatted

# Used for caching bot information
bot_cache = {}
# Creates the Bedrock client
bedrock_client = boto3.client('bedrock-runtime', region_name=AWS_REGION)
bedrock = Bedrock(model_id=FOUNDATION_MODEL_ID, client=bedrock_client)
bedrock.model_kwargs = {'temperature': 0.0,
                        'stop_sequences':['<STOP>']}
# Creates the Lex client
lex_client = boto3.client('lexv2-models', region_name=AWS_REGION)

# Output parser for the LLM
parser = PydanticOutputParser(pydantic_object=IntentOutput)

def lambda_handler(event, context):
    """Handles Amazon Lex events"""
    logger.debug("Received event: %s", event)
    logger.info("Input: %s", event["inputTranscript"])
    
    #Retrieve Lex bot configuration
    logger.debug("Retrieving bot information")
    lex_bot = LexBot(lex_client,event)
    
    logger.debug("Building prompt")
    llm_prompt = LLMLexPrompt(event,lex_bot)

    logger.debug(("Predicting response"))
    response = bedrock.predict(llm_prompt.prompt_formatted)
    logger.info("Raw Response: %s", response)

    logger.debug("Parsing response")
    parsed_response = parser.parse(response)
    logger.debug("Parsed Response: %s", parsed_response)

    logger.debug("Looking up intent id")
    predicted_intent = lex_bot.intents_utterances[parsed_response.intent_id]['intent_name']
    
    
    # Get the name intent name of the fallback intent
    for intent_id in lex_bot.intents_utterances:
        if lex_bot.intents_utterances[intent_id]['parentIntentSignature'] == 'AMAZON.FallbackIntent':
            fallback_intent = lex_bot.intents_utterances[intent_id]['intent_name']
            logging.debug("Default fallback intent: %s", fallback_intent)
    
    logger.info("Predicted Intent Name: %s, Confidence: %s", predicted_intent, parsed_response.confidence)
    
    # Intent recognized and confidence above threshold
    if predicted_intent in lex_bot.intent_names_ids \
        and parsed_response.confidence > PREDICTION_CONFIDENCE \
        and predicted_intent != fallback_intent:

        logger.info("Delegating. Parsed response: %s", predicted_intent)
        return lex_bot.delegate(predicted_intent)

    # Intent not recognized or confidence below threshold
    logger.info("Low Confidence or Predicted Intent %s not \
            found in list of intents:\n %s", predicted_intent, lex_bot.intent_names_ids)
    predicted_intent = fallback_intent
    parsed_response.confidence = '1.00'
    logger.info("Closing. Parsed Response: %s", parsed_response)
    return lex_bot.close_fallback(fallback_intent)