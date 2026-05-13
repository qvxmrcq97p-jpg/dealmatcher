@isTest
private class BatchUpdateTheContactRecordsTest {
    static testmethod void test() {
        // Create test accounts to be updated by batch
        List<Lead> lstLead = new List<Lead>();
        for (Integer i=0;i<100;i++) {
            Lead leadObj = new Lead(LastName = 'Account ' + i,Company = 'Comp ' + i);
            lstLead.add(leadObj);
        }
        insert lstLead;
        
        Test.startTest();
        BatchUpdateTheContactRecords b = new BatchUpdateTheContactRecords();
        Database.executeBatch(b);
        Test.stopTest();
        Lead[] accUpdatedList = [SELECT Id, Name FROM Lead];
       // System.assert(accUpdatedList[0].Name.Contains('sfdcpoint'));
    }
}