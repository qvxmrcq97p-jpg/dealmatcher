global class BatchUpdateTheContactRecords implements Database.Batchable<sObject> {
    global Database.QueryLocator start(Database.BatchableContext BC) {     
        String query = 'Select ID from lead';
        return Database.getQueryLocator(query);
    }
    
    global void execute(Database.BatchableContext BC, List<lead> leadList) {
        Map<String,String> mapRecordType = new Map<String,String>();
        mapRecordType.put('Buyer','0124x000000A2idAAC');
        mapRecordType.put('Seller','0124x000000A2iYAAS');
       /* for(lead obj : leadList) {    
            if(obj.Status__c != ''){
                obj.Status = obj.Status__c;                
            }
            if(obj.Lead_Type__c != ''){
                obj.RecordTypeId = mapRecordType.get(obj.Lead_Type__c);
            } else {
                obj.RecordTypeId = mapRecordType.get('Seller');  
            }
        }
        try {
            update leadList;    
        } catch(Exception e) {
            System.debug(e);
        }      */
    }   
    
    global void finish(Database.BatchableContext BC) {
        //sendEmail('Batch Update Email','Leads Updated Successfully!');
    }
    
  /*  public static void sendEmail(String subject, STring body){
        Messaging.SingleEmailMessage message = new Messaging.SingleEmailMessage();
        message.toAddresses = new String[] { 'saadahmadmughal@gmail.com' };
            message.optOutPolicy = 'FILTER';
        message.subject = subject;
        message.plainTextBody = body;
        Messaging.SingleEmailMessage[] messages = new List<Messaging.SingleEmailMessage> {message};
            Messaging.SendEmailResult[] results = Messaging.sendEmail(messages);
    }*/
}